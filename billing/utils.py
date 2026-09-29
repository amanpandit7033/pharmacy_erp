def amount_to_words(amount):
    """
    Converts a numerical decimal/float amount into Indian currency words.
    e.g. 336.00 -> 'Three Hundred Thirty Six Rupees Only'
         14440.50 -> 'Fourteen Thousand Four Hundred Forty Rupees and Fifty Paise Only'
    """
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        return ""

    if amount == 0:
        return "Zero Rupees Only"

    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
            "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def convert_two_digits(num):
        if num < 20:
            return ones[num]
        else:
            unit = ones[num % 10]
            return (tens[num // 10] + (" " + unit if unit else "")).strip()

    def convert_three_digits(num):
        hundreds = num // 100
        remainder = num % 100
        res = ""
        if hundreds > 0:
            res += ones[hundreds] + " Hundred"
        if remainder > 0:
            if res:
                res += " "
            res += convert_two_digits(remainder)
        return res

    integer_part = int(amount)
    paise_part = round((amount - integer_part) * 100)

    # Indian numbering system: Crore, Lakh, Thousand, Remainder
    crore = integer_part // 10000000
    integer_part %= 10000000
    lakh = integer_part // 100000
    integer_part %= 100000
    thousand = integer_part // 1000
    remainder = integer_part % 1000

    parts = []
    if crore > 0:
        parts.append(convert_two_digits(crore) + " Crore")
    if lakh > 0:
        parts.append(convert_two_digits(lakh) + " Lakh")
    if thousand > 0:
        parts.append(convert_two_digits(thousand) + " Thousand")
    if remainder > 0:
        parts.append(convert_three_digits(remainder))

    words = " ".join(parts).strip()
    if not words:
        words = "Zero"

    res = f"{words} Rupees"
    if paise_part > 0:
        res += f" and {convert_two_digits(paise_part)} Paise"
    res += " Only"
    return res
