import re
from typing import Optional, Tuple, List

# Regex for matching codes like G1234, TB98213, etc.
# Matches prefix G, F, TB, Y (case-insensitive) followed by digits, with word boundaries.
CODE_PATTERN = re.compile(r"\b(G|F|TB|Y)(\d+)\b", re.IGNORECASE)

# English keywords using word boundaries to prevent substring collisions (e.g., "painter" -> "paid")
ENG_SEND_PATTERN = re.compile(r"\b(cut|paid)\b", re.IGNORECASE)
ENG_RECEIVE_PATTERN = re.compile(r"\b(receive|received)\b", re.IGNORECASE)

# Khmer keywords (checked as substrings, as Khmer does not use space word boundaries)
KHMER_SEND_KEYWORDS = ["កាត់រួចរាល់", "បានកាត់", "កាត់រួច", "រួចរាល់", "កាត់"]
KHMER_RECEIVE_KEYWORDS = ["បានទទួលរួច", "បានទទួល", "ទទួល", "បាន"]

def parse_message(text: str) -> Optional[Tuple[List[str], str]]:
    """
    Parses a message to find one or more valid codes and determine their status.
    
    Returns (list_of_normalized_codes, status) if both are found, where status is 'SENT' or 'RECEIVED'.
    Returns None if no valid match is found or if the message is ambiguous (has both or neither).
    
    Examples:
    """
    if not text:
        return None
        
    # 1. Search for all valid codes
    matches = CODE_PATTERN.finditer(text)
    codes = []
    seen = set()
    for match in matches:
        prefix, digits = match.groups()
        normalized_code = f"{prefix.upper()}{digits}"
        if normalized_code not in seen:
            codes.append(normalized_code)
            seen.add(normalized_code)
            
    if not codes:
        return None
    
    # 2. Check for status keywords
    is_send = False
    is_receive = False
    
    # Check English send keywords
    if ENG_SEND_PATTERN.search(text):
        is_send = True
        
    # Check Khmer send keywords
    for kw in KHMER_SEND_KEYWORDS:
        if kw in text:
            is_send = True
            break
            
    # Check English receive keywords
    if ENG_RECEIVE_PATTERN.search(text):
        is_receive = True
        
    # Check Khmer receive keywords
    for kw in KHMER_RECEIVE_KEYWORDS:
        if kw in text:
            # Special check to prevent "បាន" from colliding when it is part of a send action (e.g. "បានកាត់")
            if kw == "បាន" and is_send:
                continue
            is_receive = True
            break
            
    # Return codes and status only if we have an unambiguous classification
    if is_send and not is_receive:
        return codes, "SENT"
    elif is_receive and not is_send:
        return codes, "RECEIVED"
        
    return None
