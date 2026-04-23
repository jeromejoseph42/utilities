import pyperclip
import pyautogui
import re
import keyboard
import winsound
import time
import threading


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
    else:
        print("Congrats! End of Script")
        winsound.Beep(400, 300)

def go_back():
    global i, last_sync_state
    now = time.time()

    # If recently did smart sync -> undo whole block
    if last_sync_state and now - last_sync_state["time"] < 5:
        chars = last_sync_state["chars_pasted"]
        for _ in range(chars):
            keyboard.send("backspace")
        i = last_sync_state["old_i"]
        print("[UNDO] Smart sync reverted.")
        last_sync_state = None
        return

    # Otherwise normal single step back
    if i > 0:
        i -= 1
        print(f"Back to [{i}] {repr(tokens[i])}")
        
last_sync_state = None
def smart_sync():
    global i, tokens, last_sync_state

    annotation_text = pyperclip.paste()
    if not annotation_text.strip():
        print("Clipboard empty.")
        return

    old_i = i
    sync_time = time.time()

    # Normalize
    script_text = re.sub(r'\s+', ' ', "".join(tokens).strip().lower())
    annotation_text_clean = re.sub(r'\s+', ' ', annotation_text.strip().lower())

    target_word_index = None

    # =====================================================
    # FULL MATCH
    # =====================================================
    pos = script_text.find(annotation_text_clean)

    if pos != -1:
        words_before = len(re.findall(r'\b\w+\b', script_text[:pos + len(annotation_text_clean)]))
        target_word_index = words_before

    # =====================================================
    # FALLBACK MATCH
    # =====================================================
    if target_word_index is None:
        script_words = re.findall(r'\b\w+\b', script_text)
        ann_words = re.findall(r'\b\w+\b', annotation_text_clean)

        for window in [8, 6, 4, 3, 2]:
            if len(ann_words) < window:
                continue

            snippet = ann_words[-window:]

            for idx in range(len(script_words)):
                if script_words[idx:idx+window] == snippet:
                    target_word_index = idx + window
                    break
            if target_word_index:
                break

    if target_word_index is None:
        print("[SYNC] Could not match.")
        return

    # =====================================================
    # Convert word index -> token index
    # =====================================================
    word_count = 0
    target_token_index = None

    for t_idx, token in enumerate(tokens):
        if re.match(r'\w+', token):
            word_count += 1
        if word_count == target_word_index:
            target_token_index = t_idx + 1
            break

    if target_token_index is None:
        print("[SYNC] Conversion failed.")
        winsound.Beep(240, 500)
        return

    # =====================================================
    # PASTE EVERYTHING FROM CURRENT i -> TARGET
    # =====================================================
    paste_block = "".join(tokens[i:target_token_index])

    keyboard.write(paste_block)

    # Save rollback state
    last_sync_state = {
        "old_i": old_i,
        "chars_pasted": len(paste_block),
        "time": sync_time
    }

    i = target_token_index

    print(f"[SYNC] Pasted up to index {i}")

def copy_and_sync():
    # Select all and copy
    keyboard.send("ctrl+a")
    time.sleep(0.05)
    keyboard.send("ctrl+c")
    time.sleep(0.05)

    smart_sync()
    keyboard.release("ctrl")
    
def read_highlight():
    # Select all and copy
    keyboard.send("ctrl+shift+right")
    time.sleep(0.05)

auto_running = False
def auto_loop():
    global auto_running
    if auto_running:
        print("[AUTO] Already running.")
        return
    auto_running = True

    def worker():
        global auto_running
        time.sleep(0.05)
        for key in ("ctrl", "shift", "alt", "f9"):
            try: keyboard.release(key)
            except: pass
        time.sleep(5)

        pause_event = threading.Event()
        pause_hook = keyboard.hook_key("pause", lambda e: e.event_type == "down" and pause_event.set(), suppress=True)

        try:
            while auto_running:
                time.sleep(5)
                pyautogui.click(702, 325);  time.sleep(1.5)
                keyboard.send("ctrl+p");    time.sleep(0.2)
                pyautogui.click(702, 632);  time.sleep(1)
                copy_and_sync();            time.sleep(0.5)
                print("[AUTO] PAUSE to submit | ESC to stop")
                pause_event.clear()
                pause_event.wait()
                if not auto_running: break
                pyautogui.click(1100, 1010);    time.sleep(1)
                pyautogui.click(1146, 622);     time.sleep(5)
                keyboard.send("f6");            time.sleep(0.3)
                keyboard.send("ctrl+c");        time.sleep(0.4)
                url = pyperclip.paste()
                match = re.search(r'task=(\d+)', url)
                if not match: print("[AUTO] No task ID."); break
                pyperclip.copy(re.sub(r'task=\d+', f'task={int(match.group(1))+1}', url))
                keyboard.send("ctrl+v");    time.sleep(0.3)
                keyboard.send("enter");     time.sleep(4)
        finally:
            keyboard.unhook(pause_hook)
            auto_running = False
            print("[AUTO] Ended")

    threading.Thread(target=worker, daemon=True).start()

print("Controls:")
print("F8 -> paste next")
print("F7 -> go back")
print("F9 -> SMART SYNC")
print("ctrl+F9 -> select all, copy and SMART SYNC")
print("ctrl+shift+F9 -> select all, copy and SMART SYNC")
print("Numpad decimal -> Reading Highlighter")
print("ESC -> quit\n")
print(f"Starting with [{i}] {repr(tokens[i])}")

keyboard.add_hotkey("F8", paste_next)
keyboard.add_hotkey("F7", go_back)
keyboard.add_hotkey("F9", smart_sync)
keyboard.add_hotkey("ctrl+f9", copy_and_sync)
keyboard.add_hotkey("ctrl+shift+f9", auto_loop, suppress=True, trigger_on_release=True)
keyboard.add_hotkey("decimal", read_highlight)

keyboard.wait("esc")