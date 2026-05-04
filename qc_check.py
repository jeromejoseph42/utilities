import pyautogui
import keyboard
import time
import threading

running = False
pause_event = threading.Event()

# =========================
# Submit function
# =========================
def pause_action():
    print("Pause action triggered")
    pyautogui.click(275, 855)
    time.sleep(0.5)
    pyautogui.click(1172, 1005)
    time.sleep(1)
    pyautogui.click(1158, 623)
    time.sleep(5)

# =========================
# Main loop
# =========================
def click_loop():
    global running
    while running:
        # First clicks
        pyautogui.click(1603, 816)
        keyboard.send("ctrl+p")
        time.sleep(1)
        pyautogui.click(1174, 668)

        # Wait 35s, break early if Pause pressed
        pause_event.clear()
        start_time = time.time()
        while time.time() - start_time < 35:
            if pause_event.is_set():
                break
            time.sleep(0.1)

        # Always run pause_action after 35s OR on early interrupt
        pause_action()
        pause_event.clear()

# =========================
# Toggle with Decimal key
# =========================
def trigger_pause():
    pause_event.set()  # Signal the loop to break early

def toggle():
    global running
    running = not running
    print("Running:", running)
    if running:
        threading.Thread(target=click_loop, daemon=True).start()

keyboard.add_hotkey("decimal", toggle)
keyboard.add_hotkey("pause", trigger_pause)  # Sets event; loop handles the action

print("Press Decimal to start/stop.")
print("Press Pause anytime to trigger pause action early.")
keyboard.wait()