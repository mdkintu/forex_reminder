//+------------------------------------------------------------------+
//| FAIR_Sync.mq5                                                    |
//| Reports this account's latest trade OPEN time to FAIR (Forex     |
//| Account Inactivity Reminder) so the inactivity countdown resets  |
//| by itself.                                                       |
//|                                                                  |
//| READ-ONLY: it never opens, closes or modifies orders or trades.  |
//| Leave "Algo Trading" OFF, and run it in a terminal logged in     |
//| with the account's INVESTOR (read-only) password.                |
//| Run it on your own computer (the one you trade from, or another  |
//| on the same network), NOT a VPS: some prop firms ban or flag VPS |
//| logins. Check your firm's EA rules first: FundedNext CFD $50k+   |
//| bans "any automated tools", so ask them in writing.              |
//|                                                                  |
//| Setup                                                            |
//|  1. Tools > Options > Expert Advisors: tick "Allow WebRequest    |
//|     for listed URL" and add your FAIR site, e.g.                 |
//|     https://fair.tergym.com                                      |
//|  2. Open this file in MetaEditor and compile it (F7).            |
//|  3. Drag "FAIR_Sync" from the Navigator onto any chart.          |
//|     One terminal per account (MT5 is logged into one at a time). |
//|  4. On FAIR, the account's number must equal this MT5 login.     |
//|                                                                  |
//| It reports on start, on every new deal, and every                |
//| HeartbeatMinutes. Trades placed from your phone or another PC    |
//| are picked up too: the terminal reads the account's history from |
//| the broker's server.                                             |
//+------------------------------------------------------------------+
#property copyright   "FAIR"
#property version     "1.00"
#property description "Reports the latest trade open time to FAIR. Never trades."

input string FairUrl          = "__FAIR_URL__"; // FAIR sync URL (from your FAIR profile)
input string SyncKey          = "__FAIR_KEY__"; // Your FAIR MT5 sync key (keep it private)
input int    HeartbeatMinutes = 15;             // Check in with FAIR at least this often
input int    LookbackDays     = 400;            // How far back to look for the last trade

#define EA_VERSION "1.0"

ulong    g_reported_deal = 0;    // newest open deal FAIR has acknowledged
datetime g_last_report   = 0;    // local time of the last report attempt that got an answer

//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringFind(FairUrl, "__FAIR") >= 0 || StringFind(SyncKey, "__FAIR") >= 0 ||
      StringLen(FairUrl) == 0 || StringLen(SyncKey) == 0)
     {
      Print("FAIR: FairUrl / SyncKey are not set. Download the EA again from your FAIR ",
            "profile page (it comes pre-filled), or paste them into the EA inputs.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   EventSetTimer(60);
   Report(true);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   Report(false);
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
      Report(false);
  }

//+------------------------------------------------------------------+
//| Newest deal that OPENED a position (buy/sell, entry IN or INOUT). |
//| Returns its ticket (0 if none) and its time in server time.       |
//+------------------------------------------------------------------+
ulong LatestOpenDeal(datetime &deal_time)
  {
   deal_time = 0;
   ulong best = 0;
   datetime now = TimeTradeServer();
   if(!HistorySelect(now - (datetime)((long)LookbackDays * 86400), now + 86400))
      return(0);

   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      long type  = HistoryDealGetInteger(ticket, DEAL_TYPE);
      long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)
         continue;                       // skip balance, credit, commission rows
      if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_INOUT)
         continue;                       // closes don't count: firms count trades placed
      datetime t = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      if(t >= deal_time)
        {
         deal_time = t;
         best = ticket;
        }
     }
   return(best);
  }

//+------------------------------------------------------------------+
//| Broker server time minus UTC, rounded to the nearest 15 minutes.  |
//+------------------------------------------------------------------+
long ServerOffsetSeconds()
  {
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   return((long)MathRound(diff / 900.0) * 900);
  }

//+------------------------------------------------------------------+
string JsonEscape(string s)
  {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   return(s);
  }

//+------------------------------------------------------------------+
//| "https://host/path" -> "https://host" (what to whitelist).        |
//+------------------------------------------------------------------+
string SiteRoot(string url)
  {
   int start = StringFind(url, "://");
   if(start < 0)
      return(url);
   int slash = StringFind(url, "/", start + 3);
   return(slash < 0 ? url : StringSubstr(url, 0, slash));
  }

//+------------------------------------------------------------------+
//| Send the latest open time when it changed, on start (force) or    |
//| when the heartbeat is due.                                        |
//+------------------------------------------------------------------+
void Report(bool force)
  {
   datetime deal_time;
   ulong deal = LatestOpenDeal(deal_time);
   bool heartbeat_due = (long)(TimeLocal() - g_last_report) >= (long)HeartbeatMinutes * 60;
   if(!force && deal == g_reported_deal && !heartbeat_due)
      return;

   string open_utc = "null";
   if(deal > 0)
      open_utc = IntegerToString((long)deal_time - ServerOffsetSeconds());

   string body = "{\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) +
                 ",\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"" +
                 ",\"last_open_utc\":" + open_utc +
                 ",\"deal\":" + IntegerToString((long)deal) +
                 ",\"ea\":\"" + EA_VERSION + "\"}";

   char data[];
   char reply[];
   string reply_headers;
   int len = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(data, len - 1);           // drop the terminating zero
   string headers = "Content-Type: application/json\r\n" +
                    "Authorization: Bearer " + SyncKey + "\r\n" +
                    "X-FAIR-Key: " + SyncKey + "\r\n";

   ResetLastError();
   int status = WebRequest("POST", FairUrl, headers, 10000, data, reply, reply_headers);
   string text = CharArrayToString(reply, 0, WHOLE_ARRAY, CP_UTF8);

   if(status == -1)
     {
      int err = GetLastError();
      if(err == 4014 || err == 4006)     // 4006: what MT5 returns for an unlisted IP-address URL
         Print("FAIR: MT5 blocked the request (error ", err, "). Go to Tools > Options > Expert Advisors, tick ",
               "\"Allow WebRequest for listed URL\" and add ", SiteRoot(FairUrl));
      else
         Print("FAIR: could not reach FAIR (error ", err, "). Retrying in a minute.");
      Comment("FAIR Sync: not connected (see the Experts tab)");
      return;
     }

   g_last_report = TimeLocal();
   if(status == 200)
     {
      if(force || deal != g_reported_deal)
         Print("FAIR: synced. ", text);
      g_reported_deal = deal;
      Comment("FAIR Sync: OK, last check-in ", TimeToString(TimeLocal(), TIME_DATE | TIME_MINUTES));
      return;
     }

   Print("FAIR: server answered ", status, ": ", text);
   Comment("FAIR Sync: error ", status, " (see the Experts tab)");
   if(status == 401 || status == 404)
      g_reported_deal = deal;            // needs a fix on FAIR; retry at the next heartbeat
  }
//+------------------------------------------------------------------+
