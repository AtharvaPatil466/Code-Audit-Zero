import React, { useState, useEffect, useRef } from 'react';
import './App.css';

// ─── Data & Constants ───
const ENDPOINTS = [
  { id: 'wallet', path: '/wallet', x: 26, y: 18 },
  { id: 'vault', path: '/vault', x: 44, y: 10 },
  { id: 'users', path: '/users', x: 64, y: 19 },
  { id: 'buy', path: '/buy', x: 68, y: 50 },
  { id: 'admin', path: '/admin/withdraw', x: 20, y: 52 },
  { id: 'login', path: '/login', x: 34, y: 72 },
  { id: 'debug', path: '/debug', x: 52, y: 65 },
];

const EVENTS_POOL = [
  { agent: "RED", action: "PROBE", node: "admin", msg: "GET /admin/withdraw → 200 OK", result: "EXPOSED" },
  { agent: "RED", action: "EXPLOIT", node: "vault", msg: "POST /vault/withdraw {amt:-99990}", result: "DRAINED" },
  { agent: "RED", action: "RECON", node: "debug", msg: "Discovered /api/debug endpoint", result: "MAPPED" },
  { agent: "RED", action: "EXPLOIT", node: "users", msg: "GET /users/3 → secret_key leaked", result: "DRAINED" },
  { agent: "RED", action: "PROBE", node: "wallet", msg: "GET /wallet → balance: $100", result: "MAPPED" },
  { agent: "RED", action: "CURIOSITY", node: "buy", msg: "ICM novelty spike on /buy", result: "EXPLORING" },
  { agent: "RED", action: "EXPLOIT", node: "login", msg: "Brute force on /login: 200 attempts", result: "EXPOSED" },

  { agent: "BLUE", action: "DETECT", node: null, msg: "Burst rate anomaly: 14 req/s detected", result: "FLAGGED" },
  { agent: "BLUE", action: "PATCH", node: "vault", msg: "Generated fix: input validation (6 lines)", result: "PATCHING" },
  { agent: "BLUE", action: "VERIFY", node: "vault", msg: "Z3: balance >= 0 → UNSAT", result: "PROVEN" },
  { agent: "BLUE", action: "DETECT", node: null, msg: "SQL injection pattern on /users", result: "FLAGGED" },
  { agent: "BLUE", action: "PATCH", node: "users", msg: "Rotated credentials, new UUID key", result: "PATCHING" },
  { agent: "BLUE", action: "VERIFY", node: "buy", msg: "Z3: qty > 0 constraint → UNSAT", result: "PROVEN" },
  { agent: "BLUE", action: "PATCH", node: "admin", msg: "Admin token rotated: new key deployed", result: "PATCHING" },

  { agent: "GOLD", action: "JUDGE", node: null, msg: "Mutation test 47/47 survived", result: "PASS" },
  { agent: "GOLD", action: "FUZZ", node: null, msg: "id='; DROP TABLE-- → 422 Validation", result: "PASS" },
  { agent: "GOLD", action: "JUDGE", node: null, msg: "Exploit replay → 403 Blocked", result: "PASS" },
];

function rand(min, max) { return Math.random() * (max - min) + min; }

// ─── Internal Components ───
function Sparkline({ data, color }) {
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const points = data.map((v, i) => `${(i / (data.length - 1)) * 100},${24 - ((v - min) / (max - min)) * 24}`).join(' ');
  return (
    <svg width="100%" height="24" viewBox="0 0 100 24" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" opacity="0.8" />
    </svg>
  );
}

export default function App() {
  const [running, setRunning] = useState(false);
  const [demoPanel, setDemoPanel] = useState(false);



  // Scores & States
  const [redScore, setRedScore] = useState(0);
  const [blueScore, setBlueScore] = useState(0);
  const [redStatus, setRedStatus] = useState('IDLE');
  const [blueStatus, setBlueStatus] = useState('IDLE');
  const [events, setEvents] = useState([]);

  // Persistent Node States
  // e.g. { wallet: 'idle', vault: 'attacking', ... }
  const [nodeStates, setNodeStates] = useState(
    ENDPOINTS.reduce((acc, ep) => ({ ...acc, [ep.id]: 'idle' }), {})
  );

  // Stats Counters
  const [stats, setStats] = useState({ attempts: 0, patches: 0, verdicts: 0 });
  const prevStats = useRef(stats);
  const [statsAnim, setStatsAnim] = useState({ attempts: false, patches: false, verdicts: false });

  // Score Update Trackers
  const prevRed = useRef(redScore);
  const prevBlue = useRef(blueScore);
  const [redPop, setRedPop] = useState(false);
  const [bluePop, setBluePop] = useState(false);

  // Timer
  const [timeStr, setTimeStr] = useState("00:00:00:00");
  const startTimeObj = useRef(Date.now());
  const timerInt = useRef(null);

  // Sparklines
  const [redRew, setRedRew] = useState(Array.from({ length: 20 }, () => rand(10, 50)));
  const [redEnt, setRedEnt] = useState(Array.from({ length: 20 }, () => rand(10, 50)));
  const [redNov, setRedNov] = useState(Array.from({ length: 20 }, () => rand(10, 50)));

  // Score Pops
  useEffect(() => {
    if (redScore !== prevRed.current) {
      setRedPop(true); setTimeout(() => setRedPop(false), 250);
      setRedRew(s => [...s.slice(1), rand(20, 80)]);
      setRedEnt(s => [...s.slice(1), rand(10, 40)]);
      setRedNov(s => [...s.slice(1), rand(10, 60)]);
    }
    prevRed.current = redScore;
  }, [redScore]);

  useEffect(() => {
    if (blueScore !== prevBlue.current) {
      setBluePop(true); setTimeout(() => setBluePop(false), 250);
    }
    prevBlue.current = blueScore;
  }, [blueScore]);

  // Stats Animation tracking
  useEffect(() => {
    if (stats.attempts !== prevStats.current.attempts) { setStatsAnim(s => ({ ...s, attempts: true })); setTimeout(() => setStatsAnim(s => ({ ...s, attempts: false })), 300); }
    if (stats.patches !== prevStats.current.patches) { setStatsAnim(s => ({ ...s, patches: true })); setTimeout(() => setStatsAnim(s => ({ ...s, patches: false })), 300); }
    if (stats.verdicts !== prevStats.current.verdicts) { setStatsAnim(s => ({ ...s, verdicts: true })); setTimeout(() => setStatsAnim(s => ({ ...s, verdicts: false })), 300); }
    prevStats.current = stats;
  }, [stats]);

  // Feed Scroll
  const feedRef = useRef(null);
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [events]);

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === '`') setDemoPanel(p => !p);
      else if (demoPanel) {
        if (e.key.toLowerCase() === 'r') { setRedScore(s => s + 30); triggerRandom('RED'); }
        if (e.key.toLowerCase() === 'b') { setBlueScore(s => s + 30); triggerRandom('BLUE'); }
        if (e.key === '0') {
          setRedScore(0); setBlueScore(0);
          setNodeStates(ENDPOINTS.reduce((acc, ep) => ({ ...acc, [ep.id]: 'idle' }), {}));
        }
        if (e.key.toLowerCase() === 'g') { triggerRandom('GOLD'); }
        if (e.key.toLowerCase() === 'v') { setBlueScore(350); setRedScore(80); }
        if (e.key.toLowerCase() === 'x') { setRedScore(350); setBlueScore(80); }
        if (e.key.toLowerCase() === 's') { setRunning(r => !r); }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [demoPanel]);

  const triggerRandom = (agentTarget) => {
    const pool = EVENTS_POOL.filter(e => e.agent === agentTarget);
    if (!pool.length) return;
    const ev = pool[Math.floor(Math.random() * pool.length)];
    applyEvent(ev);
  };

  const applyEvent = (ev) => {
    if (ev.agent === "RED") {
      const points = ev.reward !== undefined ? Math.floor(ev.reward * 100) : Math.floor(rand(12, 22));
      if (ev.result === "EXPOSED") {
        // Red only scores on SUCCESSFUL exploits
        setRedScore(s => s + Math.max(0, points));
        setRedStatus("ATTACKING"); setBlueStatus("IDLE");
      } else if (ev.result === "BLOCKED") {
        // Blue gets credit for every attack its patches block
        setBlueScore(s => s + Math.floor(rand(8, 15)));
        setBlueStatus("DEFENDING");
      }
    }
    if (ev.agent === "BLUE") {
      const points = ev.action === "PATCH" ? 5000 : 1000;
      setBlueScore(s => s + points);
      setBlueStatus("DEFENDING"); setRedStatus("IDLE");
    }
    if (ev.agent === "GOLD" && ev.result === "PASS") {
      setBlueScore(s => s + 2000);
    }

    // Node State Machine
    if (ev.node) {
      setNodeStates(prev => {
        const curr = prev[ev.node];
        let nextState = curr;

        if (ev.agent === 'RED') {
          // If already patched and exploited again -> compromised
          if (curr === 'patched' && ev.action === 'EXPLOIT') nextState = 'compromised';
          else nextState = 'attacking';
        }
        else if (ev.agent === 'BLUE') {
          if (ev.action === 'PATCH') nextState = 'patched';
          if (ev.action === 'VERIFY') nextState = 'verified';
        }
        return { ...prev, [ev.node]: nextState };
      });
    }

    setStats(s => ({
      attempts: s.attempts + 1,
      patches: ev.action === 'PATCH' ? s.patches + 1 : s.patches,
      verdicts: ev.agent === 'GOLD' ? s.verdicts + 1 : s.verdicts
    }));

    setEvents(p => [{ ...ev, id: Date.now() + Math.random(), time: new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) }, ...p].slice(0, 60));
  };

  // Timer logic
  useEffect(() => {
    if (running) {
      startTimeObj.current = Date.now();
      timerInt.current = setInterval(() => {
        const diff = Date.now() - startTimeObj.current;
        const h = Math.floor(diff / 3600000).toString().padStart(2, '0');
        const m = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
        const s = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');
        const ms = Math.floor((diff % 1000) / 10).toString().padStart(2, '0');
        setTimeStr(`${h}:${m}:${s}:${ms}`);
      }, 30);
    } else {
      clearInterval(timerInt.current);
    }
    return () => clearInterval(timerInt.current);
  }, [running]);

  // ─── LIVE BACKEND ENGINE LOOP (SSE) ───
  useEffect(() => {
    if (!running) return;

    // Use explicit IPv4 loopback because MacOS browsers often fail on IPv6 localhost resolution (connection refused)
    const evtSource = new EventSource("http://127.0.0.1:8000/stream");

    evtSource.onopen = () => console.log("SSE Stream Connected to AI Backend!");

    evtSource.onmessage = (event) => {
      try {
        let raw;
        try {
          raw = JSON.parse(event.data);
        } catch (parseError) {
          raw = event.data; // Fallback for raw string broadcasts
        }

        // RED AGENT PAYLOAD (From environment.py - structured JSON)
        if (typeof raw === 'object' && raw.agent_id !== undefined && raw.action_id !== undefined) {
          applyEvent({
            agent: "RED",
            action: raw.action_id >= 5 ? "EXPLOIT" : "PROBE",
            node: raw.endpoint.replace('/', '').split('/')[0] || "unknown", // heuristic
            msg: `${raw.method} ${raw.endpoint} → ${raw.status_code}`,
            result: raw.status_code < 400 ? "EXPOSED" : "BLOCKED",
            reward: raw.reward
          });
        }

        // BLUE/GOLD PAYLOADS (From patcher.py/judge.py string broadcasts)
        else if (typeof raw === 'string') {
          if (raw === "PATCH_DEPLOYED") {
            applyEvent({ agent: "BLUE", action: "PATCH", node: "vault", msg: "Blue Agent deployed patch", result: "PATCHING" });
          } else if (raw === "THREAT_DETECTED") {
            applyEvent({ agent: "BLUE", action: "DETECT", node: "users", msg: "Suspicious pattern flagged", result: "FLAGGED" });
          } else if (raw.startsWith("VERDICT_")) {
            applyEvent({ agent: "GOLD", action: "JUDGE", node: "gold", msg: raw, result: "PASS" });
          }
        }
      } catch (e) {
        console.error("SSE Feed Logic Error:", e, event.data);
      }
    };

    evtSource.onerror = (err) => {
      console.error("EventSource failed:", err);
    };

    return () => evtSource.close();
  }, [running]);

  // ─── BLUE AGENT STATE POLLER (reliable fallback for SSE drops) ───
  const lastPatchCountRef = useRef(0);
  useEffect(() => {
    if (!running) return;
    // Wait 20s before first poll — let Red Agent build a lead on screen first
    const startDelay = setTimeout(() => {
      const pollInterval = setInterval(async () => {
        try {
          const res = await fetch("http://127.0.0.1:8000/api/blue_state");
          if (res.ok) {
            const data = await res.json();
            const newPatches = (data.patch_count || 0) - lastPatchCountRef.current;
            if (newPatches > 0) {
              for (let i = 0; i < newPatches; i++) {
                applyEvent({ agent: "BLUE", action: "DETECT", node: "users", msg: "Threat pattern detected", result: "FLAGGED" });
                applyEvent({ agent: "BLUE", action: "PATCH", node: data.last_endpoint || "vault", msg: `Blue Agent deployed patch #${lastPatchCountRef.current + i + 1}`, result: "PATCHING" });
              }
              lastPatchCountRef.current = data.patch_count || 0;
            }
          }
        } catch (e) { /* backend reloading, ignore */ }
      }, 3000);
      // Store interval ID for cleanup
      startDelay._intervalId = pollInterval;
    }, 20000);
    return () => {
      clearTimeout(startDelay);
      if (startDelay._intervalId) clearInterval(startDelay._intervalId);
    };
  }, [running]);

  // SVG Dimensions tracking
  const graphRef = useRef(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const handleResize = () => {
      if (!graphRef.current) return;
      const { width, height } = graphRef.current.getBoundingClientRect();
      setDims({ w: width, h: height });
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // ─── CRITICAL MATH: V16 EXPONENTIAL BACKGROUND ───
  // Step 1: Get scores
  const total = Math.max(redScore + blueScore, 1);
  const redRatio = redScore / total;   // 0.0 to 1.0
  const blueRatio = blueScore / total;   // 0.0 to 1.0

  const isActive = running || redScore > 0 || blueScore > 0;

  // Step 2: Apply exponential curve (power of 3)
  const redPower = Math.pow(redRatio, 3);
  const bluePower = Math.pow(blueRatio, 3);

  // Step 3: Normalize so they don't both dim
  const maxPower = Math.max(redPower, bluePower, 0.001);
  const redNorm = redPower / maxPower;   // 0.0 to 1.0
  const blueNorm = bluePower / maxPower;   // 0.0 to 1.0

  // Step 4: Map to opacity and scale with WIDE ranges
  const redOpacity = 0.12 + redNorm * 0.78; // 0.12 to 0.90
  const blueOpacity = 0.12 + blueNorm * 0.78; // 0.12 to 0.90
  const redScale = 0.65 + redNorm * 0.65; // 0.65 to 1.30
  const blueScale = 0.65 + blueNorm * 0.65; // 0.65 to 1.30

  // Diagonal angle: 100deg (red total domination) to 150deg (blue total domination)
  const splitAngle = Math.round(125 + (blueNorm - redNorm) * 25);
  // Shift the gradient color stops to let the winning color consume the screen
  const shiftOffset = Math.round((redNorm - blueNorm) * 28);

  // Standby overrides — both fully vivid at equal start
  const standby = !isActive;
  const finalRedOpacity = standby ? 0.85 : redOpacity;
  const finalBlueOpacity = standby ? 0.85 : blueOpacity;
  const finalRedScale = standby ? 1.0 : redScale;
  const finalBlueScale = standby ? 1.0 : blueScale;
  const finalAngle = standby ? 125 : splitAngle;
  const finalShift = standby ? 0 : shiftOffset;

  const redPct = (redScore / total * 100).toFixed(1);
  const bluePct = (blueScore / total * 100).toFixed(1);

  return (
    <div style={{
      width: '100vw', height: '100vh',
      overflow: 'hidden', position: 'relative',
      fontFamily: 'Rajdhani, sans-serif'
    }}>
      <style>{CSS}</style>
      {/* LAYER 0: Background: 3 layers, z-index 0 */}
      <div style={{ position: 'fixed', inset: 0, zIndex: 0 }}>

        {/* LAYER 1: Base diagonal — fills 100% always */}
        <div style={{
          position: 'absolute',
          inset: 0,
          background: `linear-gradient(
            ${finalAngle}deg,
            #7A0000  0%,
            #600000 ${Math.max(0, Math.min(100, 18 + finalShift))}%,
            #7A0040 ${Math.max(0, Math.min(100, 38 + finalShift))}%,
            #6B006B ${Math.max(0, Math.min(100, 46 + finalShift))}%,
            #40007A ${Math.max(0, Math.min(100, 54 + finalShift))}%,
            #000060 ${Math.max(0, Math.min(100, 72 + finalShift))}%,
            #00007A 100%
          )`,
          transition: 'background 0.6s ease-in-out',
        }} />

        {/* LAYER 2: Red orb — purely saturated color */}
        <div style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(
            ellipse 120% 110% at 0% 0%,
            rgba(180, 15, 15, 0.95)  0%,
            rgba(130,  0,  0, 0.85) 20%,
            rgba( 80,  0,  0, 0.60) 42%,
            rgba( 40,  0,  0, 0.25) 65%,
            transparent              82%
          )`,
          opacity: finalRedOpacity,
          transform: `scale(${finalRedScale})`,
          transformOrigin: '0% 0%',
          transition: 'opacity 0.6s ease-in-out, transform 0.6s ease-in-out',
          animation: !isActive ? 'redBreathe 4s ease-in-out infinite' : 'none',
        }} />

        {/* LAYER 3: Blue orb — purely saturated color */}
        <div style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(
            ellipse 120% 110% at 100% 100%,
            rgba(15, 40, 180, 0.95)  0%,
            rgba( 0, 20, 130, 0.85) 20%,
            rgba( 0, 10,  80, 0.60) 42%,
            rgba( 0,  5,  40, 0.25) 65%,
            transparent               82%
          )`,
          opacity: finalBlueOpacity,
          transform: `scale(${finalBlueScale})`,
          transformOrigin: '100% 100%',
          transition: 'opacity 0.6s ease-in-out, transform 0.6s ease-in-out',
          animation: !isActive ? 'blueBreathe 6s ease-in-out infinite' : 'none',
        }} />

        {/* LAYER 4: Center collision glow */}
        <div style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(
            ellipse 55% 55% at 50% 50%,
            rgba(140, 0, 140, 0.45)  0%,
            rgba(100, 0, 100, 0.30) 35%,
            transparent              65%
          )`,
          transition: 'opacity 0.6s ease-in-out',
          opacity: 1 - Math.abs(redNorm - blueNorm) * 0.8,
        }} />
      </div>

      {/* LAYER 1: All UI — always in front of background */}
      <div style={{
        position: 'relative',
        zIndex: 1,
        width: '100vw',
        height: '100vh',
        display: 'grid',
        gridTemplateColumns: '240px 1fr 240px',
        gridTemplateRows: '56px 40px 1fr 180px 48px',
        gridTemplateAreas: `
          "topbar   topbar   topbar"
          "scorebar scorebar scorebar"
          "red      center   blue"
          "red      feed     blue"
          "botbar   botbar   botbar"
        `,
        gap: '6px',
        padding: '6px',
        boxSizing: 'border-box',
        overflow: 'hidden',
      }}>

        {/* ─── TOP BAR (Section 10) ─── */}
        <div className="top-bar" style={{ gridArea: 'topbar' }}>
          <div className="tl">
            <h1 className="logo">CODE-AUDIT-ZERO</h1>
            <span className="sub">AUTONOMOUS CYBER RANGE</span>
          </div>
          <div className="tc">
            <div className={`pill-status ${running ? 'active' : 'standby'}`}>
              <div className="dot" /> {running ? '● AGENTS ACTIVE' : '● STANDBY'}
            </div>
            <div className="epoch">EPOCH 4 · PHASE 2</div>
          </div>
          <div className="tr">
            <div className="timer">{timeStr}</div>
            <button className="btn-halt" onClick={() => { if (window.confirm("Halt simulation?")) setRunning(false); }}>HALT</button>
          </div>
        </div>

        {/* ─── SCORE BAR (Section 5) ─── */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 16px',
          height: 40,
          background: 'rgba(6, 3, 14, 0.58)',
          backdropFilter: 'blur(20px) saturate(140%)',
          gridArea: 'scorebar',
          borderRadius: 8
        }}>
          <span style={{ fontFamily: 'Orbitron', fontSize: 12, color: '#EF4444' }}>RED</span>
          <span className={`${redPop ? 'scale-anim' : ''}`} style={{ fontFamily: 'Orbitron', fontSize: 20, color: '#EF4444', fontWeight: 700, textShadow: '0 0 20px rgba(239,68,68,0.5)' }}>
            {Math.floor(redScore)}
          </span>

          <div style={{
            flex: 1, height: 6, borderRadius: 3,
            background: 'rgba(255,255,255,0.08)',
            position: 'relative', overflow: 'hidden'
          }}>
            {/* Red fills from left */}
            <div style={{
              position: 'absolute', left: 0, top: 0,
              height: '100%',
              width: redPct + '%',
              background: 'linear-gradient(90deg, #7F1D1D, #EF4444)',
              borderRadius: '3px 0 0 3px',
              transition: 'width 1.2s ease-in-out'
            }} />
            {/* Blue fills from right */}
            <div style={{
              position: 'absolute', right: 0, top: 0,
              height: '100%',
              width: bluePct + '%',
              background: 'linear-gradient(270deg, #1D4ED8, #60A5FA)',
              borderRadius: '0 3px 3px 0',
              transition: 'width 1.2s ease-in-out'
            }} />
          </div>

          <span className={`${bluePop ? 'scale-anim' : ''}`} style={{ fontFamily: 'Orbitron', fontSize: 20, color: '#60A5FA', fontWeight: 700, textShadow: '0 0 20px rgba(96,165,250,0.5)' }}>
            {Math.floor(blueScore)}
          </span>
          <span style={{ fontFamily: 'Orbitron', fontSize: 12, color: '#60A5FA' }}>BLUE</span>
        </div>

        {/* ─── RED PANEL (Section 6) ─── */}
        <div style={{
          gridArea: 'red',
          width: '100%',
          height: '100%',
          overflowY: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '12px',
          background: 'rgba(6, 3, 14, 0.58)',
          backdropFilter: 'blur(20px) saturate(140%)',
          borderRadius: '12px',
          borderLeft: '2px solid rgba(220,38,38,0.5)',
          zIndex: 10
        }}>
          <div className="p-head">
            <span className="p-title">RED AGENT</span>
            <span className={`p-badge ${redStatus === 'ATTACKING' ? 'bd-red' : 'bd-idle'}`}>{redStatus}</span>
          </div>

          <div className={`huge-score ${redPop ? 'scale-anim' : ''}`}>{Math.floor(redScore)}</div>

          <div className="stats-2x2">
            <div className="stat-card">
              <span className="sc-v">{redRew[19]?.toFixed(1)}</span>
              <span className="sc-l">REWARD</span>
              <div className="svg-box"><Sparkline data={redRew} color="#EF4444" /></div>
            </div>
            <div className="stat-card">
              <span className="sc-v">{redEnt[19]?.toFixed(1)}</span>
              <span className="sc-l">ENTROPY</span>
              <div className="svg-box"><Sparkline data={redEnt} color="#F97316" /></div>
            </div>
            <div className="stat-card">
              <span className="sc-v">{redNov[19]?.toFixed(1)}</span>
              <span className="sc-l">NOVELTY</span>
              <div className="svg-box"><Sparkline data={redNov} color="#EC4899" /></div>
            </div>
            <div className="stat-card">
              <span className="sc-v text-red-v">{Math.floor(redScore / 10)}</span>
              <span className="sc-l">BREACHES</span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span className="v-lbl">ATTACK VECTOR</span>
            <span className="v-val">PPO · ICM · LSTM</span>
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span className="v-lbl">THREAT SATURATION</span><span className="v-lbl">{(redRatio * 100).toFixed(0)}%</span></div>
            <div className="prog-bar"><div className="prog-fill" style={{ background: '#DC2626', width: `${redRatio * 100}%` }} /></div>
          </div>

          <div className="curric-row">
            <span className="cr-done">✓ 01 SCOUT</span>
            <span className="cr-act text-red-v">02 EXPLOIT</span>
            <span className="cr-tbd">03 SWARM</span>
          </div>
        </div>



        {/* ─── CENTER AREA ─── */}
        <div style={{
          gridArea: 'center',
          display: 'grid',
          gridTemplateRows: '1fr 220px',
          gridTemplateAreas: `
            "graph"
            "feed"
          `,
          gap: '6px',
          minHeight: 0,
          overflow: 'hidden'
        }}>

          {/* NETWORK GRAPH (Section 8) */}
          <div className="network-graph" ref={graphRef} style={{ gridArea: 'graph', position: 'relative', width: '100%', height: '100%', minHeight: 0, overflow: 'hidden' }}>
            {/* EXACT SVG LINES (Section 3) */}
            <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 2, overflow: 'visible' }}>
              {ENDPOINTS.map(ep => {
                const state = nodeStates[ep.id];

                const nodePixelX = (ep.x / 100) * dims.w;
                const nodePixelY = (ep.y / 100) * dims.h;
                const originX = 0;
                const originY = dims.h * 0.5;

                // Red attacking line
                if (state === 'attacking') return (
                  <line key={ep.id + '-atk'} x1={originX} y1={originY} x2={nodePixelX} y2={nodePixelY} stroke="#EF4444" strokeWidth="1.5" strokeDasharray="8 5" opacity="0.6">
                    <animate attributeName="stroke-dashoffset" from="100" to="0" dur="1.2s" repeatCount="indefinite" />
                  </line>
                );

                // Blue patched line
                if (state === 'patched' || state === 'compromised') return (
                  <line key={ep.id + '-pat'} x1={nodePixelX} y1={nodePixelY} x2={dims.w} y2={dims.h * 0.5} stroke={state === 'compromised' ? '#991B1B' : '#60A5FA'} strokeWidth="1.5" strokeDasharray="none" opacity="0.5">
                    <animate attributeName="opacity" values="0.35;0.55;0.35" dur="2s" repeatCount="indefinite" />
                  </line>
                );

                // Gold verified line
                if (state === 'verified') return (
                  <line key={ep.id + '-ver'} x1={nodePixelX} y1={nodePixelY} x2={dims.w} y2={dims.h * 0.5} stroke="#D97706" strokeWidth="1" opacity="0.5" />
                );

                return null;
              })}
            </svg>

            {/* NODES */}
            {ENDPOINTS.map(ep => {
              const s = nodeStates[ep.id];
              let nc = 'node-idle';
              if (s === 'attacking') nc = 'node-atk anim-shake';
              if (s === 'patched') nc = 'node-pat';
              if (s === 'verified') nc = 'node-ver anim-pulse';
              if (s === 'compromised') nc = 'node-cmp';

              return (
                <div key={ep.id} className={`graph-node ${nc}`} style={{ left: `${ep.x}%`, top: `${ep.y}%` }}>
                  <div className="hex-shape">
                    {s === 'patched' && <span style={{ position: 'absolute', top: '-8px', fontSize: '10px' }}>🛡</span>}
                    {s === 'compromised' && <span style={{ fontSize: '16px', fontWeight: 'bold', color: '#FCA5A5' }}>✕</span>}
                  </div>
                  <span className="lbl">{ep.path}</span>
                </div>
              )
            })}
          </div>

          {/* EVENT FEED (Section 9) */}
          <div className="event-feed" ref={feedRef} style={{ gridArea: 'feed', height: '220px', minHeight: 0, overflowY: 'auto' }}>
            {events.map(ev => {
              let rb = 'rp-def'; const lres = ev.result.toLowerCase();
              if (['pass', 'proven', 'blocked'].includes(lres)) rb = 'rp-grn';
              else if (['fail', 'exposed', 'drained'].includes(lres)) rb = 'rp-red';
              else if (['patching', 'mapped'].includes(lres)) rb = 'rp-blu';
              else if (['flagged'].includes(lres)) rb = 'rp-org';
              else if (['exploring'].includes(lres)) rb = 'rp-pur';

              return (
                <div key={ev.id} className="feed-row row-enter">
                  <span className="er-time">{ev.time}</span>
                  <span className={`er-ag ag-${ev.agent}`}>{ev.agent}</span>
                  <span className="er-act">{ev.action}</span>
                  <span className="er-msg">{ev.msg}</span>
                  <span className={`er-res ${rb}`}>{ev.result}</span>
                </div>
              )
            })}
          </div>
        </div>

        {/* ─── BLUE PANEL (Section 7) ─── */}
        <div style={{
          gridArea: 'blue',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '12px',
          background: 'rgba(6, 3, 14, 0.58)',
          backdropFilter: 'blur(20px) saturate(140%)',
          borderRadius: '12px',
          borderRight: '2px solid rgba(37,99,235,0.5)',
          zIndex: 10
        }}>
          <div className="p-head">
            <span className="p-title text-blue-v">BLUE AGENT</span>
            <span className={`p-badge ${blueStatus === 'DEFENDING' ? 'bd-blue' : 'bd-idle'}`}>{blueStatus}</span>
          </div>

          <div className={`huge-score text-blue-v text-blue-shadow ${bluePop ? 'scale-anim' : ''}`}>{Math.floor(blueScore)}</div>

          <div className="stats-2x2">
            <div className="stat-card">
              <span className="sc-v text-blue-v">{(blueRatio * 100).toFixed(1)}%</span>
              <span className="sc-l text-blue-v">INTEGRITY %</span>
            </div>
            <div className="stat-card">
              <span className="sc-v text-blue-v">{Math.floor(blueScore / 5)}</span>
              <span className="sc-l text-blue-v">PATCHES</span>
            </div>
            <div className="stat-card">
              <span className="sc-v text-blue-v">{Math.floor(blueScore / 12)}</span>
              <span className="sc-l text-blue-v">BLOCKS</span>
            </div>
            <div className="stat-card">
              <span className="sc-v text-blue-v">{Math.floor(blueScore / 8)}</span>
              <span className="sc-l text-blue-v">Z3 PROOFS</span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span className="v-lbl text-blue-v">DEFENSE MATRIX</span>
            <span className="v-val">CodeBERT · DeepSeek · Z3</span>
          </div>

          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span className="v-lbl text-blue-v">SYSTEM INTEGRITY</span><span className="v-lbl text-blue-v">{(blueRatio * 100).toFixed(0)}%</span></div>
            <div className="prog-bar"><div className="prog-fill" style={{ background: blueRatio < 0.25 ? '#EF4444' : blueRatio < 0.5 ? '#F97316' : '#2563EB', width: `${blueRatio * 100}%` }} /></div>
          </div>

          <div className="gold-card" style={{
            marginTop: 'auto',
            background: 'rgba(6, 3, 14, 0.58)',
            backdropFilter: 'blur(20px) saturate(140%)',
            border: '1px solid rgba(217,119,6,0.3)',
            borderRadius: '8px',
            padding: '10px 12px',
          }}>
            <div className="gs-hd">⚖ GOLD JUDGE</div>
            <div className="gs-val">98.4% <span className="gs-sub">PATCH SURVIVAL</span></div>
            <div className="gs-bot">
              <span style={{ color: '#22c55e' }}>21 PASS</span>
              <span style={{ color: '#EF4444' }}>9 FAIL</span>
            </div>
          </div>
        </div>

        {/* ─── BOTTOM BAR (Section 10) ─── */}
        <div style={{
          gridArea: 'botbar',
          height: '48px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          background: 'rgba(6, 3, 14, 0.58)',
          backdropFilter: 'blur(20px) saturate(140%)',
          borderRadius: '10px',
          borderTop: '1px solid rgba(255,255,255,0.06)'
        }}>
          <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-start' }}>
            <div className="bb-left">
              <span className="svc-dot"><div className="sd online" /> APP 1</span>
              <span className="svc-dot"><div className="sd online" /> APP 2</span>
              <span className="svc-dot"><div className="sd online" /> REDIS</span>
              <span className="svc-dot"><div className="sd offline" /> MAML</span>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <button
              onClick={() => setRunning(!running)}
              style={{
                width: 160,
                height: 36,
                borderRadius: 18,
                fontFamily: 'Orbitron',
                fontSize: 13,
                fontWeight: 700,
                cursor: 'pointer',
                background: running
                  ? 'linear-gradient(135deg, rgba(180,20,20,0.7), rgba(20,60,180,0.7))'
                  : 'linear-gradient(135deg, rgba(120,20,20,0.6), rgba(20,40,120,0.6))',
                border: running
                  ? '1px solid rgba(255,255,255,0.3)'
                  : '1px solid rgba(255,255,255,0.2)',
                color: 'white',
              }}
              className={running ? 'btn-engage eg-pls' : 'btn-engage'}
            >
              {running ? '■ DISENGAGE' : '▶ ENGAGE'}
            </button>
          </div>

          <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
            <div className="bb-right" style={{ fontFamily: 'Share Tech Mono', fontSize: 11, color: 'rgba(255,255,255,0.4)', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className={statsAnim.attempts ? 't-up' : ''}>Attempts: {stats.attempts}</span> |
              <span className={statsAnim.patches ? 't-up' : ''}>Patches: {stats.patches}</span> |
              <span className={statsAnim.verdicts ? 't-up' : ''}>Verdicts: {stats.verdicts}</span>
            </div>
          </div>
        </div>

        {/* ─── DEBUG OVERLAY ─── */}
        {demoPanel && (
          <div className="debug-panel">
            <strong>DEBUG</strong><br />
            [R] +30 RED<br />[B] +30 BLUE<br />
            [G] GOLD flash<br />[0] RESET<br />
            [v] BLUE win<br />[x] RED win
          </div>
        )}

      </div>
    </div>
  );
}

// ─── CSS INJECTION ───
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Rajdhani:wght@400;500;600;700&display=swap');

  :root {
    --gap-xs: 4px; --gap-sm: 8px; --gap-md: 12px; --gap-lg: 16px; --gap-xl: 20px;
    --radius-sm: 4px; --radius-md: 8px; --radius-lg: 12px; --radius-pill: 20px;
  }

  html, body, #root { margin: 0; padding: 0; width: 100vw; height: 100vh; overflow: hidden; background: #080812; color: #fff; }
  * { box-sizing: border-box; }

    /* ─── SECTION 1: V16 BREATHING ANIMATIONS ─── */
  @keyframes redBreathe {
    0%,100% { opacity: 0.75; transform: scale(0.97); }
    50%     { opacity: 0.90; transform: scale(1.04); }
  }
  @keyframes blueBreathe {
    0%,100% { opacity: 0.75; transform: scale(0.97); }
    50%     { opacity: 0.90; transform: scale(1.04); }
  }

  /* ─── SECTION 4: FULL LAYOUT GRID ─── */
  .app-shell {
    position: relative; z-index: 1; width: 100vw; height: 100vh;
    display: grid; gap: 8px; padding: 8px;
    grid-template-rows: 56px 40px 1fr 48px;
    grid-template-columns: 260px 1fr 260px;
    grid-template-areas:
      "topbar  topbar   topbar"
      "scorebar scorebar scorebar"
      "red-panel center  blue-panel"
      "botbar  botbar   botbar";
  }

  .top-bar    { grid-area: topbar; }
  .score-bar  { grid-area: scorebar; }
  .red-panel  { grid-area: red-panel; border-left: 2px solid rgba(220,38,38,0.5); }
  .blue-panel { grid-area: blue-panel; border-right: 2px solid rgba(37,99,235,0.5); }
  .center-panel { grid-area: center; display: grid; grid-template-rows: 1fr 240px; gap: 8px; min-height: 0; overflow: hidden; }
  .bottom-bar { grid-area: botbar; }

  /* Common Panel Styling */
  .panel {
    background: rgba(5, 5, 15, 0.55);
    backdrop-filter: blur(18px) saturate(150%); -webkit-backdrop-filter: blur(18px) saturate(150%);
    border-radius: 12px; border-top: 1px solid rgba(255,255,255,0.07); border-bottom: 1px solid rgba(255,255,255,0.07);
    padding: 16px; display: flex; flex-direction: column; gap: 12px; z-index: 10;
  }

  .text-red-v { color: #EF4444; }
  .text-blue-v { color: #60A5FA; }

  /* ─── SECTION 10: TOP/BOTTOM BAR ─── */
  .top-bar { background: rgba(6, 3, 14, 0.58); backdrop-filter: blur(20px) saturate(140%); border-bottom: 1px solid rgba(255,255,255,0.05); border-radius: 10px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; }
  .tl .logo { font-family: 'Orbitron'; font-size: 17px; font-weight: 700; color: white; margin: 0; }
  .tl .sub { display: block; margin-top: 1px; font-family: 'Rajdhani'; font-size: 10px; color: rgba(255,255,255,0.35); text-transform: uppercase; letter-spacing: 0.2em; }
  .tc { display: flex; flex-direction: column; align-items: center; }
  .pill-status { font-family: 'Rajdhani'; font-size: 12px; letter-spacing: 0.15em; padding: 2px 10px; border-radius: 12px; border: 1px solid; }
  .pill-status.standby { border-color: rgba(255,255,255,0.15); color: rgba(255,255,255,0.4); }
  .pill-status.active { border-color: #22c55e; color: #22c55e; animation: act-pulse 1s infinite; }
  @keyframes act-pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
  .tc .epoch { font-family: 'Rajdhani'; font-size: 10px; color: rgba(255,255,255,0.3); margin-top: 2px; }
  .tr { display: flex; align-items: center; gap: 16px; }
  .timer { font-family: 'Share Tech Mono'; font-size: 22px; color: #F59E0B; }
  .btn-halt { border: 1px solid rgba(220,38,38,0.5); color: #EF4444; background: rgba(220,38,38,0.06); font-family: 'Rajdhani'; font-weight: 700; border-radius: 4px; padding: 4px 14px; cursor: pointer; transition: 0.3s; }
  .btn-halt:hover { background: rgba(220,38,38,0.15); }

  .bottom-bar { background: rgba(5, 5, 15, 0.55); border-top: 1px solid rgba(255,255,255,0.05); border-radius: 10px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; }
  .bb-left { display: flex; gap: 12px; font-family: 'Rajdhani'; font-size: 11px; color: rgba(255,255,255,0.4); letter-spacing: 0.1em; }
  .svc-dot { display: flex; align-items: center; gap: 4px; }
  .sd { width: 6px; height: 6px; border-radius: 50%; }
  .sd.online { background: #22c55e; animation: dt-pulse 2s ease-out infinite; }
  .sd.offline { background: rgba(255,255,255,0.25); }
  @keyframes dt-pulse { 0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,0.4)} 50%{box-shadow:0 0 0 4px rgba(34,197,94,0)} }
  
  .btn-engage { width: 160px; height: 38px; border-radius: 19px; font-family: 'Orbitron'; font-size: 12px; font-weight: 700; color: white; cursor: pointer; transition: 0.3s; }
  .bt-stby { background: linear-gradient(135deg, rgba(139,26,26,0.5), rgba(26,44,139,0.5)); border: 1px solid rgba(255,255,255,0.15); }
  .bt-stby:hover { border-color: rgba(255,255,255,0.3); transform: scale(1.02); }
  .bt-act { background: linear-gradient(135deg, rgba(139,26,26,0.7), rgba(26,44,139,0.7)); border: 1px solid rgba(255,255,255,0.25); animation: eg-pls 2s ease-in-out infinite; }
  @keyframes eg-pls { 0%,100%{box-shadow:0 0 12px rgba(139,26,26,0.4),0 0 12px rgba(26,44,139,0.4);} 50%{box-shadow:0 0 24px rgba(220,38,38,0.6),0 0 24px rgba(37,99,235,0.6);} }
  
  .bb-right { font-family: 'Share Tech Mono'; font-size: 11px; color: rgba(255,255,255,0.35); display: flex; gap: 8px; align-items: center; }
  .t-up { display: inline-block; animation: t-tick 0.3s; }
  @keyframes t-tick { 0%{transform:translateY(0);} 50%{transform:translateY(-3px); opacity:0.5;} 100%{transform:translateY(0); opacity:1;} }

  /* ─── SECTION 5: SCORE BAR STYLES MOVED INLINE ─── */
  .scale-anim { animation: scanim 250ms ease-out; }
  @keyframes scanim { 0%,100%{transform:scale(1);} 50%{transform:scale(1.4);} }
  

  /* ─── SECTION 6 & 7: AGENT PANELS ─── */
  .p-head { display: flex; justify-content: space-between; align-items: center; font-family: 'Orbitron'; font-size: 13px; }
  .p-title.text-red-v { color: #EF4444; }
  .p-badge { font-family: 'Rajdhani'; font-size: 11px; font-weight: 700; border-radius: 4px; padding: 2px 8px; }
  .bd-idle { border: 1px solid rgba(255,255,255,0.2); color: rgba(255,255,255,0.4); }
  .bd-red { background: #DC2626; color: white; animation: atkbox 1s infinite; }
  .bd-blue { background: #2563EB; color: white; animation: atkbox 1s infinite; }
  @keyframes atkbox { 0%,100%{opacity:1} 50%{opacity:0.6} }
  
  .huge-score { font-family: 'Orbitron'; font-size: 72px; font-weight: 900; display: block; text-align: center; margin: 8px 0; }
  .huge-score.text-red-v { color: #EF4444; }
  .text-red-shadow { text-shadow: 0 0 30px rgba(239,68,68,0.45); }
  .text-blue-shadow { text-shadow: 0 0 30px rgba(96,165,250,0.45); }

  .stats-2x2 { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .stat-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; position: relative; overflow: hidden; height: 55px; }
  .sc-v { font-family: 'Share Tech Mono'; font-size: 18px; color: white; z-index: 2; }
  .sc-v.text-red-v { font-family: 'Orbitron'; font-size: 28px; font-weight: normal; color: #EF4444; margin-top: -4px; margin-bottom: 4px; text-align: center; display: block; }
  .sc-v.text-blue-v { color: #60A5FA; }
  .sc-l { font-family: 'Rajdhani'; font-size: 10px; color: rgba(255,255,255,0.4); text-transform: uppercase; z-index: 2; }
  .sc-l.text-blue-v { color: rgba(255,255,255,0.4); }
  .svg-box { position: absolute; bottom: 0; left: 0; width: 100%; height: 24px; z-index: 1; }

  .v-lbl { font-family: 'Rajdhani'; font-size: 10px; color: rgba(255,255,255,0.4); text-transform: uppercase; letter-spacing: 0.15em; }
  .v-val { font-family: 'Rajdhani'; font-size: 14px; color: rgba(255,255,255,0.85); }
  
  .prog-bar { height: 3px; border-radius: 2px; margin-top: 4px; background: rgba(255,255,255,0.08); overflow: hidden; }
  .prog-fill { height: 100%; transition: width 0.8s ease; }
  
  .curric-row { display: flex; justify-content: space-between; margin-top: auto; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 10px; }
  .cr-act { font-family: 'Rajdhani'; font-size: 11px; font-weight: 700; }
  .cr-done { font-family: 'Rajdhani'; font-size: 11px; color: rgba(255,255,255,0.3); }
  .cr-tbd { font-family: 'Rajdhani'; font-size: 11px; color: rgba(255,255,255,0.2); }

  .gold-card { background: rgba(5, 5, 15, 0.55); border: 1px solid rgba(217,119,6,0.25); border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
  .gs-hd { font-family: 'Orbitron'; font-size: 10px; color: #D97706; letter-spacing: 0.15em; }
  .gs-val { font-family: 'Share Tech Mono'; font-size: 32px; font-weight: 700; color: #D97706; display: flex; justify-content: space-between; align-items: baseline; }
  .gs-sub { font-family: 'Rajdhani'; font-size: 10px; color: rgba(255,255,255,0.3); font-weight: normal; }
  .gs-bot { display: flex; justify-content: space-between; font-family: 'Rajdhani'; font-size: 12px; font-weight: 700; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 6px; margin-top: 4px;}

  /* ─── SECTION 8: GRAPH ─── */
  .network-graph { position: relative; width: 100%; height: 100%; min-height: 0; overflow: hidden; background: rgba(6, 3, 14, 0.58); backdrop-filter: blur(20px) saturate(140%); border-radius: 12px; border: 1px solid rgba(255,255,255,0.07); }
  .graph-node { position: absolute; transform: translate(-50%, -50%); display: flex; flex-direction: column; align-items: center; z-index: 10; }
  
  .hex-shape { width: 56px; height: 56px; display: flex; justify-content: center; align-items: center; clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%); transition: 0.3s; }
  .lbl { position: absolute; top: calc(100% + 6px); left: 50%; transform: translateX(-50%); white-space: nowrap; font-family: 'Rajdhani'; font-size: 10px; letter-spacing: 0.05em; }
  
  .node-idle .hex-shape { background: rgba(255,255,255,0.05); border: 1.5px solid rgba(255,255,255,0.15); }
  .node-idle .lbl { color: rgba(255,255,255,0.5); }
  
  .node-atk .hex-shape { background: rgba(220,38,38,0.12); border: 2px solid #EF4444; filter: drop-shadow(0 0 16px rgba(239,68,68,0.7)) drop-shadow(0 0 32px rgba(239,68,68,0.3)); }
  .node-atk .lbl { color: #EF4444; }
  .anim-shake { animation: nxsh 0.35s ease-in-out infinite; }
  @keyframes nxsh { 0%,100%{transform:translate(-50%,-50%) rotate(0deg);} 20%{transform:translate(calc(-50% - 2px),calc(-50% + 1px)) rotate(-0.5deg);} 40%{transform:translate(calc(-50% + 2px),calc(-50% - 2px)) rotate(0.5deg);} 60%{transform:translate(calc(-50% - 1px),calc(-50% + 2px)) rotate(-0.3deg);} 80%{transform:translate(calc(-50% + 1px),calc(-50% - 1px)) rotate(0.3deg);} }
  
  .node-pat .hex-shape { background: rgba(37,99,235,0.12); border: 2px solid #60A5FA; filter: drop-shadow(0 0 16px rgba(96,165,250,0.6)) drop-shadow(0 0 32px rgba(96,165,250,0.25)); }
  .node-pat .lbl { color: #60A5FA; }
  
  .node-ver .hex-shape { background: rgba(217,119,6,0.1); border: 2px solid #D97706; filter: drop-shadow(0 0 18px rgba(217,119,6,0.7)); }
  .node-ver .lbl { color: #D97706; }
  .anim-pulse { animation: vrpls 1.5s ease-in-out infinite; }
  @keyframes vrpls { 0%,100%{filter:drop-shadow(0 0 18px rgba(217,119,6,0.7));} 50%{filter:drop-shadow(0 0 28px rgba(217,119,6,1));} }
  
  .node-cmp .hex-shape { background: rgba(153,27,27,0.2); border: 2px solid #7F1D1D; opacity: 0.6; }
  .node-cmp .lbl { color: #FCA5A5; }

  /* ─── SECTION 9: FEED ─── */
  .event-feed { background: rgba(6, 3, 14, 0.58); backdrop-filter: blur(20px) saturate(140%); border-radius: 12px; padding: 10px 12px; overflow-y: auto; display: flex; flex-direction: column; }
  .event-feed::-webkit-scrollbar { width: 3px; }
  .event-feed::-webkit-scrollbar-track { background: transparent; }
  .event-feed::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
  
  .feed-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.04); }
  .row-enter { animation: ev-enter 180ms ease-out forwards; }
  @keyframes ev-enter { from{opacity:0; transform:translateY(5px);} to{opacity:1; transform:translateY(0);} }

  .er-time { font-family: 'Share Tech Mono'; font-size: 10px; color: rgba(255,255,255,0.28); width: 72px; flex-shrink: 0; }
  .er-ag { border-radius: 3px; padding: 2px 6px; font-family: 'Rajdhani'; font-size: 10px; font-weight: 700; letter-spacing: 0.1em; border: 1px solid; }
  .ag-RED { background: rgba(220,38,38,0.18); border-color: rgba(220,38,38,0.45); color: #EF4444; }
  .ag-BLUE { background: rgba(37,99,235,0.18); border-color: rgba(37,99,235,0.45); color: #60A5FA; }
  .ag-GOLD { background: rgba(217,119,6,0.18); border-color: rgba(217,119,6,0.45); color: #D97706; }
  .er-act { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); font-family: 'Rajdhani'; font-size: 10px; color: rgba(255,255,255,0.45); padding: 2px 6px; border-radius: 3px; }
  .er-msg { font-family: 'Rajdhani'; font-size: 12px; color: rgba(255,255,255,0.78); flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  
  .er-res { border-radius: 3px; padding: 2px 6px; font-family: 'Rajdhani'; font-size: 10px; font-weight: 700; flex-shrink: 0; }
  .rp-grn { background: rgba(34,197,94,0.12); color: #22c55e; }
  .rp-red { background: rgba(220,38,38,0.12); color: #EF4444; }
  .rp-blu { background: rgba(37,99,235,0.12); color: #93C5FD; }
  .rp-org { background: rgba(245,158,11,0.12); color: #FCD34D; }
  .rp-pur { background: rgba(139,92,246,0.12); color: #C4B5FD; }
  .rp-def { background: rgba(255,255,255,0.1); color: #aaa; }

  /* ─── DEBUG ─── */
  .debug-panel { position: fixed; bottom: 60px; right: 16px; background: rgba(8,8,18,0.92); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 14px; z-index: 1000; font-family: 'Share Tech Mono'; font-size: 11px; color: rgba(255,255,255,0.6); }
`
