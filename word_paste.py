import pyperclip
import re
import keyboard

text = pyperclip.paste()

# remove line breaks
text = re.sub(r'\s*\n\s*', ' ', text)

# tokenize (words, punctuation, spaces)
tokens = re.findall(r'\w+|[^\w\s]|\s+', text)

i = 0

def paste_next():
    global i
    if i < len(tokens):
        keyboard.write(tokens[i])
        print(f"[{i}] {repr(tokens[i])}")
        i += 1

def go_back():
    global i
    if i > 0:
        i -= 1
        print(f"Back to [{i}] {repr(tokens[i])}")

print("Controls:")
print("F8 -> paste next")
print("F7 -> go back")
print("ESC -> quit\n")

keyboard.add_hotkey("F8", paste_next)
keyboard.add_hotkey("F7", go_back)

keyboard.wait("esc")