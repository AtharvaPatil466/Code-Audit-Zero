import requests
import time
import os
from colorama import Fore, Style, init

# Initialize colors for terminal
init(autoreset=True)

API_URL = "http://localhost:8000/wallet"


def fetch_stats():
    try:
        response = requests.get(API_URL, timeout=1)
        if response.status_code == 200:
            return response.json()
    except:
        return None
    return None


def run_dashboard():
    print(f"{Fore.CYAN}🚀 CODE-AUDIT ZERO: LIVE COMMAND CENTER")
    print("-" * 40)

    last_balance = None

    while True:
        data = fetch_stats()

        if data:
            current_balance = data.get("balance", 0)

            # Determine color based on balance change
            color = Fore.WHITE
            status = "STABLE"

            if last_balance is not None:
                if current_balance > last_balance:
                    color = Fore.RED + Style.BRIGHT
                    status = "VULNERABILITY EXPLOITED (MONEY STOLEN)"
                elif current_balance < last_balance:
                    color = Fore.GREEN + Style.BRIGHT
                    status = "SYSTEM RECOVERING / RESET"

            # Clear line and print update
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] {color}BALANCE: ${current_balance:<10} | STATUS: {status}")

            last_balance = current_balance
        else:
            print(f"{Fore.YELLOW}⌛ Waiting for Target API to wake up...", end="\r")

        time.sleep(1)


if __name__ == "__main__":
    try:
        run_dashboard()
    except KeyboardInterrupt:
        print(f"\n{Fore.CYAN}Scoreboard offline.")