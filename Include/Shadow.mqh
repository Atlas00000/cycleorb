//+------------------------------------------------------------------+
//| Shadow.mqh — AI OS shadow tracker (observe only)                   |
//| Simulates the engine's OCO bracket for every armed setup-day on    |
//| ticks, including sides the engine did not place (lot minimum, and  |
//| from P2 on, AI OS withholds), so withheld days have a counterfactual|
//+------------------------------------------------------------------+
#ifndef CORB_SHADOW_MQH
#define CORB_SHADOW_MQH

#include "Ledger.mqh"
#include "Health.mqh"

struct ShadowOrder
  {
   bool     active;
   string   eventId;
   string   setup;
   bool     armBuy;
   bool     armSell;
   string   withheldBuy;
   string   withheldSell;
   double   buyEntry;
   double   buySL;
   double   buyTP;
   double   sellEntry;
   double   sellSL;
   double   sellTP;
   datetime tEntryEnd;
   datetime tExit;
   int      state;          // 0 pending, +1 long, -1 short
   datetime fillTime;
   double   fill;
  };

ShadowOrder g_shadow[3];

void ShadowInit()
  {
   for(int i = 0; i < 3; i++)
      g_shadow[i].active = false;
  }

int ShadowSlot(const string setup)
  {
   return setup == "LON" ? 0 : (setup == "NY" ? 1 : 2);
  }

void ShadowFinish(const int i, const string status, const datetime t, const double exitPrice, const string how)
  {
   double r = 0.0;
   const bool filled = g_shadow[i].state != 0;
   if(filled)
     {
      const double entry = g_shadow[i].state > 0 ? g_shadow[i].buyEntry : g_shadow[i].sellEntry;
      const double sl = g_shadow[i].state > 0 ? g_shadow[i].buySL : g_shadow[i].sellSL;
      const double riskPx = MathAbs(entry - sl);
      r = riskPx > 0.0 ? g_shadow[i].state * (exitPrice - g_shadow[i].fill) / riskPx : 0.0;
      if(status == "FILLED")
         HealthAdd(r);
     }
   LedgerWriteShadow(g_shadow[i].eventId, g_shadow[i].setup, g_shadow[i].armBuy, g_shadow[i].armSell,
                     g_shadow[i].withheldBuy, g_shadow[i].withheldSell, status, g_shadow[i].state,
                     g_shadow[i].fillTime, g_shadow[i].fill, filled ? t : 0, filled ? exitPrice : 0.0, how, r, filled);
   g_shadow[i].active = false;
  }

// Arm the virtual bracket on the engine's levels. Sides the engine skipped for structural reasons
// (price already through, TP < SL) are not armed; lot-minimum and AI OS withholds are.
void ShadowStart(const OrbDecision &d)
  {
   if(g_ledShd == INVALID_HANDLE || !d.hasRange || d.decision != "ARMED")
      return;
   const int i = ShadowSlot(d.setup);
   MqlTick t;
   if(g_shadow[i].active && SymbolInfoTick(_Symbol, t))
      ShadowFinish(i, "ABANDONED", t.time, g_shadow[i].state > 0 ? t.bid : t.ask, "");
   const bool b = d.armBuy && d.skipBuy != "price_through" && d.skipBuy != "tp_lt_sl";
   const bool s = d.armSell && d.skipSell != "price_through" && d.skipSell != "tp_lt_sl";
   if(!b && !s)
      return;
   g_shadow[i].active = true;
   g_shadow[i].eventId = DecisionEventId(d);
   g_shadow[i].setup = d.setup;
   g_shadow[i].armBuy = b;
   g_shadow[i].armSell = s;
   g_shadow[i].withheldBuy = (b && !d.placedBuy) ? d.skipBuy : "";
   g_shadow[i].withheldSell = (s && !d.placedSell) ? d.skipSell : "";
   g_shadow[i].buyEntry = d.buyEntry;
   g_shadow[i].buySL = d.buySL;
   g_shadow[i].buyTP = d.buyTP;
   g_shadow[i].sellEntry = d.sellEntry;
   g_shadow[i].sellSL = d.sellSL;
   g_shadow[i].sellTP = d.sellTP;
   g_shadow[i].tEntryEnd = d.tEntryEnd;
   g_shadow[i].tExit = d.tExit;
   g_shadow[i].state = 0;
   g_shadow[i].fillTime = 0;
   g_shadow[i].fill = 0.0;
  }

// Same tick rules as the tester: buy stop fills at ask, sell stop at bid; long exits at bid, short at ask
void ShadowTick(const datetime now)
  {
   MqlTick t;
   if(!SymbolInfoTick(_Symbol, t))
      return;
   for(int i = 0; i < 3; i++)
     {
      if(!g_shadow[i].active)
         continue;
      if(g_shadow[i].state == 0)
        {
         if(now >= g_shadow[i].tEntryEnd)
            ShadowFinish(i, "NO_FILL", now, 0.0, "");
         else if(g_shadow[i].armBuy && t.ask >= g_shadow[i].buyEntry)
           {
            g_shadow[i].state = 1;
            g_shadow[i].fill = t.ask;
            g_shadow[i].fillTime = now;
           }
         else if(g_shadow[i].armSell && t.bid <= g_shadow[i].sellEntry)
           {
            g_shadow[i].state = -1;
            g_shadow[i].fill = t.bid;
            g_shadow[i].fillTime = now;
           }
         continue;
        }
      if(g_shadow[i].state > 0)
        {
         if(t.bid <= g_shadow[i].buySL)
            ShadowFinish(i, "FILLED", now, t.bid, "SL");
         else if(t.bid >= g_shadow[i].buyTP)
            ShadowFinish(i, "FILLED", now, t.bid, "TP");
         else if(now >= g_shadow[i].tExit)
            ShadowFinish(i, "FILLED", now, t.bid, "TIME");
        }
      else
        {
         if(t.ask >= g_shadow[i].sellSL)
            ShadowFinish(i, "FILLED", now, t.ask, "SL");
         else if(t.ask <= g_shadow[i].sellTP)
            ShadowFinish(i, "FILLED", now, t.ask, "TP");
         else if(now >= g_shadow[i].tExit)
            ShadowFinish(i, "FILLED", now, t.ask, "TIME");
        }
     }
  }

void ShadowCloseAll()
  {
   MqlTick t;
   const bool ok = SymbolInfoTick(_Symbol, t);
   for(int i = 0; i < 3; i++)
      if(g_shadow[i].active)
         ShadowFinish(i, "OPEN_AT_END", ok ? t.time : TimeCurrent(), ok ? (g_shadow[i].state > 0 ? t.bid : t.ask) : 0.0, "");
  }

#endif // CORB_SHADOW_MQH
