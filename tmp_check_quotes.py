
with open('static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

in_string = False
quote_char = None
escaped = False

for i, char in enumerate(content):
    if escaped:
        escaped = False
        continue
    if char == '\\':
        escaped = True
        continue
    
    if not in_string:
        if char in ("'", '"', '`'):
            in_string = True
            quote_char = char
            start_pos = i
    else:
        if char == quote_char:
            in_string = False
            quote_char = None

if in_string:
    line = content.count('\n', 0, start_pos) + 1
    print(f"Unclosed string literal starting with {quote_char} at line {line}")
else:
    print("All string literals are closed!")
