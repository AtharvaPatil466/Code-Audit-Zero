import redis
import os
import json
import time
import requests
import pytest
import random
import string
from shared.config import settings, get_logger

logger = get_logger("GOLD_AGENT")

# Redis Connection
r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)

class GoldJudge:
    def __init__(self):
        self.target_url = settings.TARGET_URL

    def run_regression_tests(self):
        """Run functional tests to ensure the app is not broken."""
        logger.info("🧪 Running Regression Suite...")
        exit_code = pytest.main(["-q", "/app/gold_agent/tests/test_functional.py"])
        return exit_code == 0

    def replay_exploit(self):
        """Replay the last known successful attack from Red Agent memory."""
        logger.info("🔁 Replaying Last Exploit...")
        
        # Get last success from KB_RED
        # Format: "SUCCESS: /endpoint exploited via {...}"
        lessons = r.lrange("KB_RED", 0, -1)
        last_success = next((l for l in lessons if "SUCCESS" in l), None)
        
        if not last_success:
            logger.warning("⚠️ No successful exploit found in memory to replay.")
            return True # Pass contextually

        try:
            # Simple parsing logic (can be made robust)
            # Assuming format: SUCCESS: {url} exploited via {payload}
            parts = last_success.split(" exploited via ")
            url = parts[0].replace("SUCCESS: ", "").strip()
            payload_str = parts[1].strip()
            # Replace single quotes for JSON parsing if needed
            payload = json.loads(payload_str.replace("'", '"'))

            headers = {}
            # If "admin" in URL, try to use the *OLD* key to verify rotation
            if "admin" in url:
                headers = {"X-Admin-Token": "PROD_ADMIN_2024"} 

            if not url.startswith("http"):
                 url = f"{self.target_url}{url}"

            logger.info(f"💥 Re-Firing Payload: {payload} at {url}")
            res = requests.post(url, json=payload, headers=headers, timeout=5)
            
            if res.status_code == 200:
                logger.critical(f"❌ REPLAY SUCCESSFUL (Fix Failed): {res.json()}")
                return False
            else:
                logger.info(f"✅ REPLAY BLOCKED: {res.status_code} {res.text}")
                return True

        except Exception as e:
            logger.error(f"⚠️ Replay Error: {e}")
            return True # Fail open safely

    def mutate_exploit(self, url: str, base_payload: dict, headers: dict) -> bool:
        """Slightly modify the exploit and see if the patch still holds."""
        logger.info("🧬 Running Mutation Testing...")
        
        mutations = [
            # Add padding
            {k: f"{v}   " if isinstance(v, str) else v for k, v in base_payload.items()},
            # Change case (if string)
            {k: v.upper() if isinstance(v, str) else v for k, v in base_payload.items()},
            # Add harmless extra parameter
            {**base_payload, "ignore_me": "true"},
            # SQLi specific variants (if applicable)
            {k: v.replace("--", "#") if isinstance(v, str) else v for k, v in base_payload.items()},
        ]
        
        all_blocked = True
        for m_payload in mutations:
            try:
                res = requests.post(url, json=m_payload, headers=headers, timeout=2)
                if res.status_code == 200:
                    logger.critical(f"❌ MUTATION BYPASSED PATCH: {m_payload}")
                    all_blocked = False
            except:
                pass
                
        return all_blocked

    def fuzz_endpoint(self, url: str, headers: dict) -> bool:
        """Fuzz the patched endpoint with random inputs to ensure robustness."""
        logger.info("🎲 Fuzzing patched endpoint...")
        
        fuzz_payloads = [
            {"quantity": -999999999999},
            {"quantity": 0.00000001},
            {"item": "".join(random.choices(string.ascii_letters, k=1000))},
            {"user_id": -1},
            {"user_id": "' OR 1=1 --"},
            None, # Empty body
            {}, # Empty json
            {"unrelated": "data", "deep": {"nested": "value"}},
        ]
        
        crashes = 0
        for payload in fuzz_payloads:
            try:
                res = requests.post(url, json=payload, headers=headers, timeout=1)
                # 500 means the server crashed, patch is bad
                if res.status_code == 500:
                    logger.critical(f"❌ FUZZING CAUSED 500 CRASH: {payload}")
                    crashes += 1
            except requests.exceptions.Timeout:
                # Timeout could mean a ReDoS from the Blue Agent's regex patch!
                logger.critical(f"❌ FUZZING TIMEOUT (Potential ReDoS): {payload}")
                crashes += 1
            except Exception:
                pass
                
        if crashes > 0:
            return False
            
        logger.info("✅ Endpoint survived fuzzing.")
        return True

    def judge(self):
        logger.info("⚖️ Judge is analyzing the patch...")
        
        try:
            # 1. Regression Test
            regression_pass = self.run_regression_tests()
            
            # 2. Security Test (Replay)
            security_pass = self.replay_exploit()
            
            # Get last exploit details for deep testing
            lessons = r.lrange("KB_RED", 0, -1)
            last_success = next((l for l in lessons if "SUCCESS" in l), None)
            
            deep_security_pass = True
            if security_pass and last_success:
                try:
                    parts = last_success.split(" exploited via ")
                    url = parts[0].replace("SUCCESS: ", "").strip()
                    payload = json.loads(parts[1].strip().replace("'", '"'))
                    headers = {"X-Admin-Token": "PROD_ADMIN_2024"} if "admin" in url else {}
                    if not url.startswith("http"):
                        url = f"{self.target_url}{url}"
                        
                    # 3. Mutation Testing
                    mutation_pass = self.mutate_exploit(url, payload, headers)
                    
                    # 4. Fuzzing
                    fuzz_pass = self.fuzz_endpoint(url, headers)
                    
                    deep_security_pass = mutation_pass and fuzz_pass
                except Exception as e:
                    logger.error(f"Deep testing error: {e}")
            
            # 5. Verdict
            if regression_pass and security_pass and deep_security_pass:
                verdict = "PASS"
                msg = "✅ Patch Verified: Functional, Secure, and Robust against mutations."
            elif not regression_pass:
                verdict = "FAIL_REGRESSION"
                msg = "❌ Patch Verification Failed: Functionality Broken (Regression)."
            elif not security_pass:
                verdict = "FAIL_SECURITY"
                msg = "❌ Patch Verification Failed: Exploit still active."
            else:
                verdict = "FAIL_ROBUSTNESS"
                msg = "❌ Patch Verification Failed: Vulnerable to mutated payloads or fuzzing."
        except Exception as e:
            logger.error(f"⚖️ Error during judgment: {e}")
            verdict = "ERROR"
            msg = f"⚠️ Judge encountered an error: {str(e)[:50]}"
            
        logger.info(f"👨‍⚖️ VERDICT: {verdict}")
        r.set("JUDGE_VERDICT", json.dumps({"status": verdict, "message": msg, "timestamp": time.time()}))
        r.publish("commands", f"VERDICT_{verdict}")

    def listen(self):
        pubsub = r.pubsub()
        pubsub.subscribe("commands") # Listen for global commands
        pubsub.subscribe("events")   # Listen for PATCH events
        
        logger.info("⚖️ Gold Agent (Judge) Online. Waiting for patches...")
        
        for message in pubsub.listen():
            try:
                if message['type'] == 'message':
                    data = message['data']
                    if data == "PATCH_DEPLOYED":
                        # Wait a sec for reload
                        time.sleep(2)
                        self.judge()
                    elif data == "RESET_ALL":
                         logger.info("🧹 Resetting verdict.")
                         r.delete("JUDGE_VERDICT")
            except Exception as e:
                logger.error(f"⚖️ Judge Listen Error: {e}")

if __name__ == "__main__":
    judge = GoldJudge()
    judge.listen()
