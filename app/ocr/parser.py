"""西班牙语单据 OCR 结果解析：识别进货单/出货单关键字段。"""
import re

from app.utils import parse_amount, parse_date, parse_document_number

DOC_COMPRA = "compra"   # 进货（采购）
DOC_VENTA = "venta"     # 出货（销售）

# 常见字段标签（大小写不敏感）
LABEL_DATE = r"(?:fecha|date|emisi[oó]n|factura\s+de|f\.)"
LABEL_NIF = r"(?:nif|cif|dni|nie|identificaci[oó]n\s+fiscal)"
LABEL_TOTAL = r"(?:importe\s+total|total\s+(?:a\s+pagar|factura|neto)?|total\b|a\s+pagar|total\s+pagado|pagar)"
LABEL_IVA = r"(?:cuota\s+iva|importe\s+iva|iva|impuesto)"
LABEL_BASE = r"(?:base\s+imponible|subtotal|base\s+1|importe\s+base|importe\s+neto)"
LABEL_QTY = r"(?:cantidad|cant\.|uds?\.?|unidades)"

# 供应商/客户标签
LABEL_SUPPLIER = r"(?:proveedor|vendedor|emisor|expedida\s+por|firmado\s+por)"
LABEL_CUSTOMER = r"(?:cliente|comprador|destinatario|a\s+favor\s+de|facturar\s+a)"

# 币种（USD=美元，VES/BS/Bs.=玻利瓦尔，统一识别为 Bs，CNY=人民币）
CURRENCY_PATTERNS = [
    ("EUR", re.compile(r"\bEUR\b|€|EUROS?\b", re.I)),
    ("USD", re.compile(r"\bUSD\b|US\s*\$|D[ÓO]LAR(?:ES)?\b", re.I)),
    ("Bs", re.compile(
        r"\bVES\b|\bVED\b|\bBSS\b|\bBsF\b|Bs\.?\s*S\.?|BOL[ÍI]VAR(?:ES)?\b"
        r"|(?<![A-Za-z0-9])Bs\.?(?![A-Za-z0-9])", re.I)),
    ("CNY", re.compile(r"\bCNY\b|\bRMB\b|[¥￥]|人民币|(?<=\d)\s*元\b")),
]
_SYMBOL_DOLLAR = re.compile(r"(?<![A-Za-z])\$")
_SYMBOL_BS = re.compile(r"(?<![A-Za-z0-9])Bs(?![A-Za-z0-9])", re.I)
_SYMBOL_YUAN = re.compile(r"[¥￥]")
_SKIP_RATE_LINE = re.compile(
    r"\b(?:tasa|tipo\s+de\s+cambio|cambio|rate)\b|汇率", re.I)


def detect_currency(texts) -> str:
    """识别单据币种，返回标准代码（EUR/USD/Bs/CNY）或空串（VES 归一为 Bs）。

    跳过汇率行；同一行出现两种及以上币种视为汇率对照行也跳过；
    按出现次数取多数。
    """
    counts = {}
    for ln in texts:
        if _SKIP_RATE_LINE.search(ln):
            continue
        hit = set()
        for code, pat in CURRENCY_PATTERNS:
            if pat.search(ln):
                hit.add(code)
        if _SYMBOL_DOLLAR.search(ln):
            hit.add("USD")
        if _SYMBOL_BS.search(ln):
            hit.add("Bs")
        if _SYMBOL_YUAN.search(ln):
            hit.add("CNY")
        if len(hit) > 1:      # 汇率对照行（如 "Bs. 36,50 / USD"）
            continue
        for code in hit:
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda c: (counts[c], c))


def detect_exchange_rate(texts) -> float:
    """识别单据上标注的汇率（如 Tasa: 36,50 / 1 USD = 785,07 Bs）。

    返回 float（该汇率表示 1 USD = X 本国货币），未识别返回 0.0。
    """
    pats = [
        # "Tasa: 36,50" / "Tasa de cambio: 36,50" / "TASA OFICIAL BCV: 785,07"
        re.compile(
            r"(?:tasa(?:\s+de\s+cambio)?|tipo\s+de\s+cambio|cambio|rate|tc)"
            r"\s*(?:oficial|bcv|d[óo]lar)?\s*[:.\-]?\s*"
            r"([\d]+(?:[\d.,]*\d)?)", re.I),
        # "1 USD = 785,07 Bs" / "1 DOLAR = 36,50 Bs"
        re.compile(
            r"1\s*(?:USD|D[ÓO]LAR(?:ES)?)\s*(?:=|a|por|equivale\s+a)\s*"
            r"([\d]+(?:[\d.,]*\d)?)\s*(?:Bs|VES|BOL[ÍI]VAR)", re.I),
        # "785,07 Bs / USD" / "Bs. 785,07 / USD"
        re.compile(
            r"(?:(?:Bs|VES)\.?\s*)?([\d]+(?:[\d.,]*\d)?)\s*(?:Bs|VES)?"
            r"\s*(?:/|por)\s*(?:USD|\$|D[ÓO]LAR)", re.I),
        # "1 USD = 7,20 CNY" / "1 美元 = 7.20 人民币"
        re.compile(
            r"1\s*(?:USD|D[ÓO]LAR(?:ES)?|美元)\s*(?:=|a|por|equivale\s+a)\s*"
            r"([\d]+(?:[\d.,]*\d)?)\s*(?:CNY|RMB|[¥￥]|人民币|元)", re.I),
        # "7,20 CNY / USD" / "¥ 7.20 / USD"
        re.compile(
            r"(?:CNY|RMB|[¥￥]|人民币)?\s*([\d]+(?:[\d.,]*\d)?)\s*"
            r"(?:CNY|RMB|[¥￥]|人民币|元)?\s*(?:/|por)\s*"
            r"(?:USD|\$|D[ÓO]LAR|美元)", re.I),
    ]
    for ln in texts:
        for pat in pats:
            m = pat.search(ln)
            if m:
                try:
                    v = parse_amount(m.group(1))
                except ValueError:
                    continue
                if 0 < v < 1000000:
                    return v
    return 0.0


def detect_direction(texts) -> str:
    """根据文本自动推断单据方向（进货/出货）。"""
    joined = "\n".join(texts).upper()
    if re.search(LABEL_SUPPLIER, joined, re.I) and not re.search(LABEL_CUSTOMER, joined, re.I):
        return DOC_COMPRA
    if re.search(LABEL_CUSTOMER, joined, re.I) and not re.search(LABEL_SUPPLIER, joined, re.I):
        return DOC_VENTA
    # "DE COMPRA" / "DE VENTA" 字样
    if "COMPRA" in joined or "FACTURA DE ENTRADA" in joined:
        return DOC_COMPRA
    if "VENTA" in joined or "FACTURA DE SALIDA" in joined:
        return DOC_VENTA
    return ""


def _first_match(pattern, lines, flags=re.I):
    for ln in lines:
        m = re.search(pattern, ln, flags)
        if m:
            return m
    return None


def extract_field_after_label(lines, label_pattern, take_next=True, max_skip=2):
    """在标签所在行或其后若干行提取字段值。"""
    for i, ln in enumerate(lines):
        if re.search(label_pattern, ln, re.I):
            m = re.search(r"(?:" + label_pattern + r")\s*[:.\-]?\s*(.+)$",
                          ln, re.I)
            if m and m.group(1).strip():
                return m.group(1).strip()
            if take_next:
                for j in range(i + 1, min(i + 1 + max_skip, len(lines))):
                    nxt = lines[j].strip()
                    if nxt and not re.search(r"^\s*[:\-–—.]+\s*$", nxt):
                        # 跳过纯数字/纯金额行（金额会在别处解析）
                        if re.fullmatch(r"[\d.,\s€¥￥\-]+", nxt):
                            continue
                        return nxt
    return ""


def extract_tax_id(lines) -> str:
    # 优先匹配委内瑞拉/南美 RIF: J-00041312-6、J000413126
    m = _first_match(
        r"\b([VEJPG]\s*-?\s*\d{5,10}\s*-?\s*\d?)\b", lines)
    if m:
        return re.sub(r"\s+", "", m.group(1)).upper()
    # 西班牙 NIF/CIF
    m = _first_match(
        r"(\b[A-Za-z][0-9]{7,8}[A-Za-z0-9]\b|\b[0-9]{8}[A-Za-z]\b)", lines)
    return m.group(1).upper() if m else ""


def extract_date(lines):
    for ln in lines:
        d = parse_date(ln)
        if d:
            return d
    return None


def extract_money(label, lines):
    """提取某标签后的金额。"""
    m = _first_match(label + r"\s*[:.\-]?\s*([\d.,\s€¥￥\-]+)", lines)
    if m:
        return parse_amount(m.group(1))
    return None


# 常见非商品行关键词（避免把地址/联系方式/金额标签误判为商品）
_NON_ITEM = re.compile(
    r"\b(?:n[ºo°]?\.?|nif|cif|nie|tel|telf|tfno|fax|ref(?:erencia)?"
    r"|total|subtotal|base|iva|impuesto|pago|pagar|efectivo|tarjeta"
    r"|vuelto|cambio|recibo|cajero|fecha|emisor|receptor|r[íi]f|rif)\b",
    re.I)


def _is_amount_token(tok):
    """判断 token 是否像金额（只含数字、逗号、点，且至少一位数字）。"""
    return bool(re.fullmatch(r"[\d.,]+", tok) and re.search(r"\d", tok))


def _amount_at(tokens, idx):
    """从 tokens 的 idx 位置尝试解析金额，成功返回（值，该 token 起始索引）。"""
    if idx < len(tokens) and _is_amount_token(tokens[idx]):
        try:
            return parse_amount(tokens[idx]), idx
        except ValueError:
            pass
    return None, idx


def _extract_item_from_line(s):
    """识别 Polar 型多列表格行，返回 dict 或 None。

    图片列序：Código Descripción Precio Unitario Cant U/M Importe Otro Margen Odes Neto Precio Liq
    OCR 输出可能把整行连一起。我们从右往左解析金额：
      price_liq（最右，通常远小于 neto，可选）, neto, importe, [unit_price]
    """
    # 去掉百分比数字（如 0,00% / 1,50%）及常见单位符号，但保留空格
    cleaned = re.sub(r"\d[\d.,]*\s*%", "", s, flags=re.I)
    cleaned = re.sub(r"%|\bBs\b|\bUSD\b|\bBsF\b", "", cleaned, flags=re.I)
    tokens = [t for t in cleaned.split() if t]
    if len(tokens) < 5:
        return None

    # 从右往左收集连续金额字段，记录（值，起始索引）
    nums = []
    idx = len(tokens) - 1
    while idx >= 0 and len(nums) < 5:
        val, start = _amount_at(tokens, idx)
        if val is None:
            break
        nums.append((val, start))
        idx = start - 1
    if len(nums) < 2:
        return None

    # nums 是从右到左的顺序：nums[0] 最右
    # 判断最右是否像 price_liq（远小于 neto）
    if len(nums) >= 3:
        rightmost = nums[0][0]
        second = nums[1][0]
        if rightmost > 0 and second > 0 and rightmost < second * 0.3:
            amount = nums[2][0]
            neto = nums[1][0]
            importe_start = nums[2][1]
        else:
            amount = nums[1][0]
            neto = nums[0][0]
            importe_start = nums[1][1]
    else:
        amount = nums[1][0]
        neto = nums[0][0]
        importe_start = nums[1][1]

    # importe 前面的 tokens：unit_price, qty, um, code, desc
    remaining = tokens[:importe_start]
    if len(remaining) < 2:
        return None

    # 解析 qty 与 um：最后应该是 qty + um（um 可选，如 STO、UND、CJ）
    um = ""
    qty_idx = len(remaining) - 1
    if re.match(r"^[A-Za-z]{1,6}$", remaining[qty_idx]):
        um = remaining[qty_idx]
        qty_idx -= 1
    if qty_idx < 0:
        return None
    try:
        qty = parse_amount(remaining[qty_idx])
    except ValueError:
        return None

    # unit_price 在 qty 前面；若解析失败，用 amount/qty 倒推
    price_idx = qty_idx - 1
    price = 0.0
    if price_idx >= 0:
        try:
            price = parse_amount(remaining[price_idx])
        except ValueError:
            pass
    if price <= 0 and qty:
        price = round(amount / qty, 2)

    # 前面是 code + desc
    head_end = price_idx if price > 0 else qty_idx
    head = remaining[:head_end]
    if not head:
        return None
    code = ""
    desc = " ".join(head)
    if re.match(r"^[A-Za-z0-9]{1,10}$", head[0]) and len(head) > 1:
        code = head[0].upper()
        desc = " ".join(head[1:])

    # 折扣以百分比表示：折让比例 = (金额 - 净额) / 金额 × 100
    if amount > 0:
        discount = round(max((amount - neto) / amount * 100, 0.0), 2)
    else:
        discount = 0.0
    return {
        "code": code,
        "desc": desc.strip(),
        "qty": qty,
        "unit_price": price,
        "amount": amount,
        "um": um,
        "discount": discount,
        "neto": neto,
    }


def extract_items(lines) -> list:
    """解析行项目：[{code, desc, qty, unit_price, amount, um, neto}]

    支持多种常见行布局：
      - 标准四列："描述  数量 x 单价   金额"
      - 标准四列："描述  数量  单价  金额"
      - 两列："描述  金额"（数量=1，单价=金额）
      - 描述单独成行，下一行是纯金额（数量=1）
      - Polar 型多列表格："H171 ARROZ 22,20 96 STO 2.131,20 ... 2.099,23 21,80"
    """
    items = []
    # 格式1： 描述  数量 x 单价   金额
    pat1 = re.compile(
        r"^\s*(.+?)\s+(\d+(?:[\d.,]*\d)?)\s*[xX×]\s*"
        r"(\d+(?:[\d.,]*\d)?)\s+(\d+(?:[\d.,]*\d)?)\s*$")
    # 格式2： 描述  数量  单价  金额
    pat2 = re.compile(
        r"^\s*(.+?)\s+(\d+(?:[\d.,]*\d)?)\s+(\d+(?:[\d.,]*\d)?)\s+"
        r"(\d+(?:[\d.,]*\d)?)\s*$")
    # 格式3： 描述  金额（两列）
    pat3 = re.compile(
        r"^\s*(.+?)\s+(\d{1,3}(?:[\d.,]*\d)?)\s*$")
    started = False
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        # 表头：进入商品区
        if re.search(
                r"^\s*(?:concepto|descripci[oó]n|art[ií]culo|detalle|producto"
                r"|mercanc[ií]a|c[oó]digo|c[oó]d)\b", s, re.I):
            started = True
            i += 1
            continue
        # 金额区（Base/Total/IVA 及之后）不再属于商品区
        if re.search(LABEL_BASE + r"|" + LABEL_TOTAL + r"|" + LABEL_IVA,
                     s, re.I):
            started = False
            i += 1
            continue
        if not started:
            i += 1
            continue
        # 跳过明显的非商品行（电话/税号/金额标签等）
        if _NON_ITEM.search(s):
            i += 1
            continue

        # 先尝试 Polar 型多列行
        polar = _extract_item_from_line(s)
        if polar:
            items.append(polar)
            i += 1
            continue

        m = pat1.match(s) or pat2.match(s)
        if m:
            desc, qty, price, amount = m.groups()
            try:
                qty = parse_amount(qty)
                price = parse_amount(price)
                amount = parse_amount(amount)
            except ValueError:
                i += 1
                continue
            if amount <= 0 and qty > 0 and price > 0:
                amount = qty * price
            items.append({"desc": desc.strip(), "qty": qty,
                          "unit_price": price, "amount": amount,
                          "um": "", "code": "", "discount": 0, "neto": amount})
            i += 1
            continue
        # 描述 + 金额（两列，数量=1）
        m = pat3.match(s)
        if m:
            desc, num = m.groups()
            desc = desc.strip()
            if len(desc) >= 2 and not re.search(r"\d\s*[xX×]\s*\d", s):
                try:
                    amount = parse_amount(num)
                except ValueError:
                    i += 1
                    continue
                if amount > 0:
                    items.append({"desc": desc, "qty": 1,
                                  "unit_price": amount, "amount": amount,
                                  "um": "", "code": "", "discount": 0, "neto": amount})
                    i += 1
                    continue
        # 描述单独成行，下一行是纯金额（数量=1）
        nxt = lines[i + 1].strip() if i + 1 < n else ""
        if (len(s) >= 2 and nxt
                and re.fullmatch(r"\d{1,3}(?:[\d.,]*\d)?", nxt)):
            try:
                amount = parse_amount(nxt)
            except ValueError:
                i += 1
                continue
            if amount > 0:
                items.append({"desc": s, "qty": 1,
                              "unit_price": amount, "amount": amount,
                              "um": "", "code": "", "discount": 0, "neto": amount})
                i += 2
                continue
        i += 1
    return items


def extract_iva(lines):
    """返回 (iva_rate, iva_amount)。优先从 "IVA 21%" 与金额提取。"""
    rate = 0.0
    amount = 0.0
    for ln in lines:
        m = re.search(r"\bIVA\b\s*(\d{1,2})\s*%", ln, re.I)
        if m:
            rate = float(m.group(1))
    # 优先精确标签："Cuota IVA: 7,94"
    for ln in lines:
        m = re.search(
            r"(?:cuota\s+iva|importe\s+iva|iva\s+cuota)\s*[:.\-]?\s*"
            r"(\d+(?:[\d.,]*\d)?)\s*[€¥￥]?", ln, re.I)
        if m:
            amount = parse_amount(m.group(1))
            break
    # 兜底："IVA 21% 7,94"（跳过税率本身）
    if amount == 0.0 and rate:
        for ln in lines:
            m = re.search(
                r"\bIVA\b\s*\d{1,2}\s*%\s*[:.\-]?\s*(\d+(?:[\d.,]*\d)?)\s*[€¥￥]?",
                ln, re.I)
            if m:
                amount = parse_amount(m.group(1))
                break
    return rate, amount


# ---------------------------------------------------------------- 主解析
def parse_document(texts: list) -> dict:
    """将 OCR 文本行解析为结构化单据字典。"""
    lines = [t.strip() for t in texts if t and t.strip()]
    if not lines:
        return {}

    joined_upper = "\n".join(lines).upper()
    doc_type = "FACTURA"
    if "ALBAR" in joined_upper:
        doc_type = "ALBARÁN"
    elif "TICKET" in joined_upper or "BOLETA" in joined_upper:
        doc_type = "TICKET"

    # 方向
    direction = detect_direction(lines)
    # 伙伴名称
    if direction == DOC_COMPRA:
        partner_label = LABEL_SUPPLIER
    elif direction == DOC_VENTA:
        partner_label = LABEL_CUSTOMER
    else:
        partner_label = LABEL_SUPPLIER + "|" + LABEL_CUSTOMER
    partner = extract_field_after_label(lines, partner_label)
    # 去掉名称里可能混入的编号/联系方式
    if partner:
        partner = re.sub(
            r"\s+(?:NIF|CIF|N[ºo°]?|TEL|TELF|TFNO|FAX)\s*[:.\-]?\s*[A-Za-z0-9\-/.]+\s*$",
            "", partner, flags=re.I).strip()

    base = extract_money(LABEL_BASE, lines)
    total = extract_money(LABEL_TOTAL, lines)
    iva_rate, iva_amount = extract_iva(lines)

    # 若 base/total 缺失但另一者存在，推算
    if total and not base:
        if iva_amount and iva_rate:
            base = total - iva_amount
        elif iva_rate:
            base = total / (1 + iva_rate / 100)
    if base and not iva_amount and iva_rate:
        iva_amount = round(base * iva_rate / 100, 2)
    if base and iva_rate and not total:
        total = round(base + iva_amount, 2)

    doc = {
        "direction": direction,           # compra / venta
        "doc_type": doc_type,
        "doc_number": parse_document_number("\n".join(lines)),
        "date": extract_date(lines),
        "partner": partner or "",
        "tax_id": extract_tax_id(lines),
        "base": base or 0.0,
        "iva_rate": iva_rate,
        "iva_amount": iva_amount or 0.0,
        "total": total or 0.0,
        "currency": detect_currency(lines),
        "exchange_rate": detect_exchange_rate(lines),
        "items": extract_items(lines),
        "raw_text": "\n".join(lines),
    }
    return doc
