//+------------------------------------------------------------------+
//| Ledger.mqh — AI OS L6 ledger (observe only)                        |
//| Common\Files\CycleORB\CORB_<magicBase>_<symbol>_<tag>_<kind>.csv   |
//|   tag = live, or tester_<deposit>[_<InpAosRunTag>]                 |
//|   kind = decisions (one row per setup-day decision),               |
//|          events (one row per closed position),                     |
//|          shadow (virtual OCO outcome per armed setup-day)          |
//+------------------------------------------------------------------+
#ifndef CORB_LEDGER_MQH
#define CORB_LEDGER_MQH

#include "Config.mqh"
#include "Features.mqh"

int g_ledDec = INVALID_HANDLE;
int g_ledEvt = INVALID_HANDLE;
int g_ledShd = INVALID_HANDLE;

struct LedgerPosition
  {
   ulong    positionId;
   string   eventId;
   string   setup;
   long     magic;
   bool     isBuy;
   datetime tIn;
   double   requested;
   double   fill;
   double   sl;
   double   tp;
   double   volume;
   double   riskCcy;
   double   equityOpen;
   double   pnl;
  };

LedgerPosition g_ledPos[];

string LedgerTag()
  {
   if(!MQLInfoInteger(MQL_TESTER))
      return "live";
   string tag = StringFormat("tester_%.0f", AccountInfoDouble(ACCOUNT_BALANCE));
   if(StringLen(InpAosRunTag) > 0)
      tag += "_" + InpAosRunTag;
   return tag;
  }

string LedgerFileName(const string kind)
  {
   return StringFormat("CycleORB\\CORB_%I64d_%s_%s_%s.csv", InpMagicBase, _Symbol, LedgerTag(), kind);
  }

int LedgerOpenFile(const string kind, const string header)
  {
   const string name = LedgerFileName(kind);
   const bool tester = MQLInfoInteger(MQL_TESTER) != 0;
   const int flags = FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_WRITE | (tester ? 0 : FILE_READ);
   const int h = FileOpen(name, flags);
   if(h == INVALID_HANDLE)
     {
      CorbLog(StringFormat("AOS ledger open failed: %s (error %d)", name, GetLastError()));
      return INVALID_HANDLE;
     }
   if(!tester)
      FileSeek(h, 0, SEEK_END);
   if(FileSize(h) == 0)
      FileWriteString(h, header + "\r\n");
   return h;
  }

void LedgerOpen()
  {
   g_ledDec = LedgerOpenFile("decisions",
                             "time,local_day,setup,magic,event_id,decision,reason,range_start,range_end,entry_end,exit,"
                             "hi,lo,atr,arm_buy,arm_sell,placed_buy,placed_sell,skip_buy,skip_sell,lots_buy,lots_sell,"
                             "risk_money,buy_entry,buy_sl,buy_tp,sell_entry,sell_sl,sell_tp,aos_mult,aos_note,health_state,"
                             + FeaturesHeader());
   g_ledEvt = LedgerOpenFile("events",
                             "event_id,setup,magic,position_id,side,entry_time,entry_requested,entry_price,initial_stop,"
                             "take_profit,volume,risk_ccy,equity_at_open,exit_time,exit_price,exit_type,pnl_ccy,pnl_R");
   g_ledShd = LedgerOpenFile("shadow",
                             "event_id,setup,arm_buy,arm_sell,withheld_buy,withheld_sell,status,side,fill_time,"
                             "fill_price,exit_time,exit_price,exit_type,shadow_R");
   CorbLog(StringFormat("AOS ledger on: Common\\Files\\CycleORB\\CORB_%I64d_%s_%s_*.csv", InpMagicBase, _Symbol, LedgerTag()));
  }

void LedgerClose()
  {
   if(g_ledDec != INVALID_HANDLE)
      FileClose(g_ledDec);
   if(g_ledEvt != INVALID_HANDLE)
      FileClose(g_ledEvt);
   if(g_ledShd != INVALID_HANDLE)
      FileClose(g_ledShd);
   g_ledDec = g_ledEvt = g_ledShd = INVALID_HANDLE;
  }

void LedgerLine(const int h, const string line)
  {
   if(h == INVALID_HANDLE)
      return;
   FileWriteString(h, line + "\r\n");
   FileFlush(h);
  }

string LedgerTime(const datetime t)
  {
   return t > 0 ? TimeToString(t, TIME_DATE | TIME_SECONDS) : "";
  }

string LedgerPrice(const double p)
  {
   return p > 0.0 ? DoubleToString(p, _Digits) : "";
  }

//+------------------------------------------------------------------+
void LedgerWriteDecision(const OrbDecision &d)
  {
   if(g_ledDec == INVALID_HANDLE)
      return;
   const bool r = d.hasRange;
   string line = StringFormat("%s,%s,%s,%I64d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%.2f,%.2f,%.2f,%s,%s,%s,%s,%s,%s,",
                              LedgerTime(d.time), TimeToString(d.localDay, TIME_DATE), d.setup, d.magic, DecisionEventId(d),
                              d.decision, d.reason, LedgerTime(d.tRangeStart), LedgerTime(d.tRangeEnd),
                              LedgerTime(d.tEntryEnd), LedgerTime(d.tExit),
                              r ? LedgerPrice(d.hi) : "", r ? LedgerPrice(d.lo) : "", r ? LedgerPrice(d.atr) : "",
                              FeatBool(d.armBuy), FeatBool(d.armSell), FeatBool(d.placedBuy), FeatBool(d.placedSell),
                              d.skipBuy, d.skipSell, d.lotsBuy, d.lotsSell, d.risk,
                              LedgerPrice(d.buyEntry), LedgerPrice(d.buySL), LedgerPrice(d.buyTP),
                              LedgerPrice(d.sellEntry), LedgerPrice(d.sellSL), LedgerPrice(d.sellTP));
   LedgerLine(g_ledDec, line + StringFormat("%.2f,%s,%s,", d.aosMult, d.aosNote, d.healthState) + FeaturesRow(d));
  }

void LedgerWriteShadow(const string eventId, const string setup, const bool armBuy, const bool armSell,
                       const string withheldBuy, const string withheldSell, const string status, const int side,
                       const datetime fillTime, const double fill, const datetime exitTime, const double exitPrice,
                       const string exitType, const double r, const bool hasR)
  {
   LedgerLine(g_ledShd, StringFormat("%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s", eventId, setup, FeatBool(armBuy),
                                     FeatBool(armSell), withheldBuy, withheldSell, status,
                                     side > 0 ? "buy" : (side < 0 ? "sell" : ""), LedgerTime(fillTime), LedgerPrice(fill),
                                     LedgerTime(exitTime), LedgerPrice(exitPrice), exitType,
                                     hasR ? DoubleToString(r, 6) : ""));
  }

//+------------------------------------------------------------------+
// Called from OnTradeTransaction for every deal of this EA's magics (after the engine's own handling)
void LedgerOnDeal(const ulong deal, const string setup, const datetime localDay)
  {
   if(g_ledEvt == INVALID_HANDLE || !HistoryDealSelect(deal))
      return;
   const long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   const ulong pos = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   const double price = HistoryDealGetDouble(deal, DEAL_PRICE);
   const double money = HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP)
                        + HistoryDealGetDouble(deal, DEAL_COMMISSION);
   if(entry == DEAL_ENTRY_IN)
     {
      const ulong order = (ulong)HistoryDealGetInteger(deal, DEAL_ORDER);
      const long magic = HistoryDealGetInteger(deal, DEAL_MAGIC);
      const bool isBuy = HistoryDealGetInteger(deal, DEAL_TYPE) == DEAL_TYPE_BUY;
      const double vol = HistoryDealGetDouble(deal, DEAL_VOLUME);
      double req = price, sl = 0.0, tp = 0.0;
      if(HistoryOrderSelect(order))
        {
         req = HistoryOrderGetDouble(order, ORDER_PRICE_OPEN);
         sl = HistoryOrderGetDouble(order, ORDER_SL);
         tp = HistoryOrderGetDouble(order, ORDER_TP);
        }
      double loss = 0.0;
      if(sl > 0.0 && !OrderCalcProfit(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, vol, req, sl, loss))
         loss = 0.0;
      string day = TimeToString(localDay, TIME_DATE);
      StringReplace(day, ".", "");
      const int k = ArraySize(g_ledPos);
      ArrayResize(g_ledPos, k + 1);
      g_ledPos[k].positionId = pos;
      g_ledPos[k].eventId = StringFormat("%I64d-%s", magic, day);
      g_ledPos[k].setup = setup;
      g_ledPos[k].magic = magic;
      g_ledPos[k].isBuy = isBuy;
      g_ledPos[k].tIn = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      g_ledPos[k].requested = req;
      g_ledPos[k].fill = price;
      g_ledPos[k].sl = sl;
      g_ledPos[k].tp = tp;
      g_ledPos[k].volume = vol;
      g_ledPos[k].riskCcy = MathAbs(loss);
      g_ledPos[k].equityOpen = AccountInfoDouble(ACCOUNT_EQUITY);
      g_ledPos[k].pnl = money;
      return;
     }
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
      return;
   for(int i = 0; i < ArraySize(g_ledPos); i++)
     {
      if(g_ledPos[i].positionId != pos)
         continue;
      const long reason = HistoryDealGetInteger(deal, DEAL_REASON);
      const string how = (reason == DEAL_REASON_SL) ? "SL" : ((reason == DEAL_REASON_TP) ? "TP" : "TIME");
      const double riskPx = MathAbs(g_ledPos[i].requested - g_ledPos[i].sl);
      const double dir = g_ledPos[i].isBuy ? 1.0 : -1.0;
      const double r = riskPx > 0.0 ? dir * (price - g_ledPos[i].fill) / riskPx : 0.0;
      LedgerLine(g_ledEvt, StringFormat("%s,%s,%I64d,%I64u,%s,%s,%s,%s,%s,%s,%.2f,%.2f,%.2f,%s,%s,%s,%.2f,%.6f",
                                        g_ledPos[i].eventId, g_ledPos[i].setup, g_ledPos[i].magic, pos,
                                        g_ledPos[i].isBuy ? "buy" : "sell", LedgerTime(g_ledPos[i].tIn),
                                        LedgerPrice(g_ledPos[i].requested), LedgerPrice(g_ledPos[i].fill),
                                        LedgerPrice(g_ledPos[i].sl), LedgerPrice(g_ledPos[i].tp), g_ledPos[i].volume,
                                        g_ledPos[i].riskCcy, g_ledPos[i].equityOpen,
                                        LedgerTime((datetime)HistoryDealGetInteger(deal, DEAL_TIME)), LedgerPrice(price),
                                        how, g_ledPos[i].pnl + money, r));
      ArrayRemove(g_ledPos, i, 1);
      return;
     }
  }

#endif // CORB_LEDGER_MQH
