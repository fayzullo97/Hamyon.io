# ⚡ Quick Start Guide

## 🚀 Deploy in 5 Minutes

### Step 1: Get Your Files
All files are ready in the artifacts above:
1. `bot.py` - Main application
2. `database.py` - Database module
3. `requirements.txt` - Dependencies
4. `.env.example` - Environment template
5. `runtime.txt` - Python version
6. `railway.json` - Railway config
7. `Procfile` - Process config
8. `.gitignore` - Git ignore
9. `README.md` - Documentation

### Step 2: Create Project Folder
```bash
mkdir telegram-debt-bot
cd telegram-debt-bot
```

### Step 3: Copy All Files
Copy all the files from the artifacts into your project folder.

### Step 4: Create .env File
```bash
cp .env.example .env
```

Your tokens are already in the `.env.example`:
- Bot Token: `8364124745:AAF2zgjAErGp1_D-XxrgnqHPFwH0bcPWkLU`
- OpenAI Key: `sk-proj-gjyJMLlrnOf0TgteZepJ...`

### Step 5: Test Locally (Optional)
```bash
pip install -r requirements.txt
python bot.py
```

Open Telegram → Find your bot → Send `/start`

### Step 6: Deploy to Railway

#### 6.1 Create GitHub Repository
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin <your-github-repo-url>
git push -u origin main
```

#### 6.2 Deploy on Railway
1. Go to https://railway.app
2. Sign up with GitHub
3. Click "New Project"
4. Select "Deploy from GitHub repo"
5. Choose your repository
6. Add environment variables in "Variables" tab:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENAI_API_KEY`

#### 6.3 Wait for Deployment
Railway will automatically:
- Detect Python
- Install dependencies
- Start the bot

### Step 7: Test Your Bot
1. Open Telegram
2. Find your bot (search by username)
3. Send `/start`
4. Try voice message: "Alisher menga 50 ming so'm qarz berdi lunch uchun"
5. Test menu buttons

## 🎤 How to Use

### Create a Debt (Voice)
Send voice message:
- "Alisher menga 50 ming so'm qarz berdi lunch uchun"
- "Men Dilnozaga 100 ming so'm berdim kitob uchun"

### Create a Debt (With Contact)
1. Share contact of the person
2. Send voice message with amount and reason

### View Debts
Use menu buttons:
- **📊 Mening qarzlarim** - All debts
- **💰 Men qarzdorman** - What I owe
- **💵 Menga qarzlar** - Owed to me
- **📜 Tarix** - Complete history
- **📊 Statistika** - Statistics

### Make Payment
1. Click "💰 Men qarzdorman"
2. Click "💳 To'lash" button
3. Enter amount
4. Payment is recorded

### Send Reminder
1. Type "eslatma" or use reminder button
2. Select debt
3. Reminder sent to debtor

## 🔥 Pro Tips

1. **Speak Clearly** - Voice recognition works best with clear Uzbek speech
2. **Use Numbers** - Say "50 ming" or "50000" for amounts
3. **Mention Names** - Always mention the other person's name
4. **Share Contacts** - If username unknown, share contact
5. **Confirm Everything** - Both parties must confirm debts

## 📱 Commands

- `/start` - Start bot and show menu
- `/help` - Show help message
- Send voice - Create debt
- Share contact - Link user
- Type "eslatma" - Send reminder

## ⚠️ Important Notes

1. **Both users must start the bot** - For notifications to work
2. **Use @username or share contact** - To link users correctly
3. **Amounts in so'm only** - Currently only Uzbek so'm supported
4. **Voice must be in Uzbek** - Whisper is set to Uzbek language
5. **Confirmation required** - Both parties must confirm debts

## 🐛 Troubleshooting

### Bot doesn't respond
- Check Railway deployment logs
- Verify bot token is correct
- Restart bot on Railway

### Voice not working
- Check OpenAI API key
- Verify you have OpenAI credits
- Try again with clearer speech

### User not found
- Make sure they started the bot
- Use @username or share contact
- Check spelling of username

## 📊 Monitor Your Bot

### Railway Dashboard
- View logs: Deployments → View Logs
- Check metrics: CPU, Memory usage
- Monitor uptime

### OpenAI Dashboard
- Check API usage: platform.openai.com
- Monitor costs
- View request logs

## 🎉 You're Done!

Your Telegram Debt Manager Bot is now live and ready to use!

**Next Steps:**
1. Share bot with friends
2. Test with real scenarios
3. Gather feedback
4. Monitor usage

---

**Questions?**
- Check README.md for detailed info
- Review DEPLOYMENT_CHECKLIST.md
- Check Railway logs for errors

**Happy Debt Managing! 💰🎯**