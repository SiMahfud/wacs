
with open('static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

stack = []
pairs = {'}': '{', ')': '(', ']': '['}
openers = pairs.values()

for i, char in enumerate(content):
    if char in openers:
        stack.append((char, i))
    elif char in pairs:
        if not stack or stack[-1][0] != pairs[char]:
            line = content.count('\n', 0, i) + 1
            if not stack:
                print(f"Extra closing '{char}' at line {line}")
            else:
                print(f"Mismatch: found '{char}' at line {line}, but expected closing for '{stack[-1][0]}' from line {content.count('\\n', 0, stack[-1][1]) + 1}")
        else:
            stack.pop()

if stack:
    for char, pos in stack:
        line = content.count('\n', 0, pos) + 1
        print(f"Unclosed opening '{char}' at line {line}")
else:
    print("All brackets are balanced!")
