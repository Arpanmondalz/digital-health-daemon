# BioDaemon 🖥️❤️
**An Autonomous "Tamagotchi" for Developer Health**

BioDaemon is a zero-friction Python utility that runs in your Windows system tray. It gamifies your posture and break habits by treating your physical energy as a “Health Bar.”

Instead of intrusive pop‑ups or manual tracking, it uses **OS‑level hooks** to detect when you lock your screen. Break duration is converted into “healing,” rewarding you for stepping away to stretch, walk, or move.

## 🚀 Features

- **Zero‑Touch Tracking:** Lock your screen (`Win + L`) to take a break—no buttons, no friction.  
- **Dynamic Health Engine:**  
  - **Work Fatigue:** +1 damage per minute of continuous work.  
  - **Smart Healing:** Non‑linear recovery. Breaks shorter than 2 minutes give no healing (anti‑cheat).  
  - **Full Reset:** A 15‑minute break restores full health.  
- **Visual Feedback:** A tray icon avatar (“Pixel”) visually degrades over time:  
  `Round` → `Slouch` → `Melt` → `Flat`.  
- **Permadeath Mechanic:** If ignored for 80 minutes, Pixel “dies,” requiring a real‑world **Resurrection Ritual** (20 jumping jacks).  
- **Silent Operation:** Only notifies you on healing (unlock) or on death—never interrupts deep work.

## 🛠️ Installation

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/BioDaemon.git
   cd BioDaemon
   ```

2. **Install Dependencies**
   ```bash
   pip install pystray pillow
   ```

3. **Run**
   ```bash
   python daemon.pyw
   ```
   *(Using `.pyw` runs silently without a console window.)*

## ⚙️ Configuration

Modify the balance values in `daemon.py`:

```python
LIMIT_ROUND = 45      # Minutes until avatar becomes "Slouch"
LIMIT_DEATH = 80      # Minutes until Permadeath
MIN_BREAK_TIME = 2    # Minimum break duration to count
FULL_RESET_TIME = 15  # Break duration for full heal
```

## 🧠 How It Works

BioDaemon uses `ctypes` to hook into **Windows Terminal Services (WTS)** and receives `WTS_SESSION_LOCK` and `WTS_SESSION_UNLOCK` events directly from the OS.  
This gives precise timing and extremely low CPU use (<0.1%) without polling.

## 🎨 Customization

Replace the 64×64 PNG icons in the project root:

- `round.png` — Healthy  
- `slouch.png` — Warning  
- `melt.png` — Critical  
- `flat.png` — Near-death  
- `tombstone.png` — Dead  

## 📄 License

MIT License. Stay healthy and have fun building.
