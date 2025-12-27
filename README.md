# Telegram Voice-Based Debt Manager Bot

Telegram bot orqali qarzlar va umumiy xarajatlarni ovozli xabar bilan boshqarish tizimi.

## 🚀 Features (MVP)

✅ **Voice Input** - Ovozli xabarlar orqali qarz yoki xarajat yaratish
✅ **Debt Creation** - Qarzlarni qayd qilish va saqlash
✅ **User Linking** - Telegram username orqali foydalanuvchilarni bog'lash
✅ **Confirmation Flow** - Har ikkala tomon tasdiqini so'rash
✅ **Notifications** - Ishtirokchilarga avtomatik xabarnomalar
✅ **Partial Payments** - Qisman to'lovlarni qo'llab-quvvatlash
✅ **Currency Support** - Uzbek so'm (UZS)

## 📋 Prerequisites

- Python 3.9+
- Telegram Bot Token
- OpenAI API Key (for Whisper)
- Railway.app account (or any hosting)

## 🔧 Local Development Setup

### 1. Clone or create project files

Create these files in your project directory:
- `bot.py` (main application)
- `database.py` (database module)
- `requirements.txt`
- `.env`

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
OPENAI_API_KEY=your_openai_api_key_here
```

### 4. Run locally

```bash
python bot.py
```

## 🚂 Deploy to Railway.app

### Step 1: Sign up to Railway
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub

### Step 2: Create new project
1. Click "New Project"
2. Select "Deploy from GitHub repo"
3. Or select "Empty Project" and upload files

### Step 3: Configure environment variables
In Railway dashboard:
1. Go to your project
2. Click on "Variables" tab
3. Add these variables:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
   - `OPENAI_API_KEY`: Your OpenAI API key

### Step 4: Deploy
Railway will automatically:
- Detect Python project
- Install dependencies from `requirements.txt`
- Start the bot using `Procfile` or `railway.json`

### Step 5: Check logs
- Click "Deployments" to see deployment status
- Click "View Logs" to monitor bot activity

## 📁 Project Structure

```
telegram-debt-bot/
├── bot.py              # Main bot application
├── database.py         # Database operations (SQLite)
├── requirements.txt    # Python dependencies
├── .env               # Environment variables (local)
├── railway.json       # Railway configuration
├── Procfile          # Process file for deployment
└── README.md         # This file
```

## 🎯 How to Use

### Starting the bot
1. Open Telegram and search for your bot
2. Send `/start` command
3. Bot will show welcome message with menu buttons

### Creating a debt via voice
1. Record a voice message in Uzbek, for example:
   - "Alisher menga 50,000 so'm qarz berdi lunch uchun"
   - "Men Dilnoza bilan kafe uchun 150,000 so'm xarjladim"
2. Bot will transcribe and parse the information
3. Bot will ask for any missing information
4. Confirm the details
5. Other party will receive notification to confirm

### Using menu buttons
- **📊 My Debts** - View all your debts
- **💰 I Owe** - See what you owe to others
- **💵 Owed to Me** - See what others owe you
- **📜 History** - View complete history

## 🔐 Security & Privacy

- Data is visible only to involved users
- All debts require explicit confirmation from both parties
- User identity verified via Telegram
- History is immutable (cannot be edited, only cancelled)

## 🐛 Troubleshooting

### Bot not responding
- Check Railway logs for errors
- Verify environment variables are set correctly
- Ensure bot token is valid

### Voice transcription failing
- Check OpenAI API key is valid
- Verify you have credits in OpenAI account
- Check language is set to Uzbek (uz)

### Database errors
- SQLite file will be created automatically
- For production, consider PostgreSQL on Railway

## 📊 Database Schema

### Users
- user_id (PRIMARY KEY)
- username
- first_name, last_name
- created_at

### Debts
- id (PRIMARY KEY)
- creator_id, creditor_id, debtor_id
- amount, currency
- reason
- status (pending/active/paid/cancelled)
- confirmation flags

### Payments
- id (PRIMARY KEY)
- debt_id
- payer_id, amount
- confirmed

### Notifications
- id (PRIMARY KEY)
- user_id, debt_id
- message, type
- read status

## 🔄 Future Features (Phase 2)

- [ ] Group expenses with auto-split
- [ ] Automatic and manual reminders
- [ ] Multi-language support (Russian, English)
- [ ] Export summaries (PDF, Excel)
- [ ] Statistics and analytics
- [ ] Payment integrations

## 📝 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token from @BotFather | ✅ Yes |
| `OPENAI_API_KEY` | OpenAI API key for Whisper transcription | ✅ Yes |

## 🆘 Support

If you encounter issues:
1. Check Railway logs
2. Verify all environment variables
3. Test bot locally first
4. Check OpenAI API usage limits

## 📄 License

Private project - All rights reserved

---

**Created for managing debts and shared expenses via Telegram voice messages** 🎤💰# Hamyon.io
# Hamyon.io
# Hamyon.io
