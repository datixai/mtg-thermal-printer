# MTG Printer — Web Dashboard (Vercel)

Remote web dashboard for the Datix AI MTG Thermal Card Printer.
Deployable to Vercel from GitHub in one click.

## 🚀 Deploy to Vercel

### Option A — One click (recommended)
1. Push the repo to GitHub
2. Go to [vercel.com](https://vercel.com) → New Project
3. Import your GitHub repo
4. **Set Root Directory to `web`** (important!)
5. Framework: **Other**
6. Click **Deploy**

### Option B — Vercel CLI
```bash
cd web
npx vercel --prod
```

## 🔧 How it works

The Vercel site is a **static HTML dashboard** that connects to your
Raspberry Pi's local Flask API over your Wi-Fi network.

First time you open the Vercel URL:
1. It asks for your Pi's IP address (e.g. `192.168.1.45`)
2. Saves it in your browser's localStorage
3. All API calls go directly from your browser → Pi

**The Pi and your phone/laptop must be on the same Wi-Fi network.**

## 📡 Requirements

- Pi running `sudo systemctl start mtg-printer.service`
- Pi and your browser device on the same Wi-Fi
- Pi's port 5000 must be accessible (not firewalled)

To allow port 5000:
```bash
sudo ufw allow 5000/tcp
```

## 🏗️ Project structure

```
web/
├── index.html     ← Full dashboard (single file, no dependencies)
├── vercel.json    ← Vercel config
├── package.json   ← Minimal package for Vercel detection
└── README.md      ← This file
```

No build step. No npm install. No framework. Pure HTML/CSS/JS.
Loads instantly. Works on mobile.
