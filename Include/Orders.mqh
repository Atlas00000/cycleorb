//+------------------------------------------------------------------+
//| Orders.mqh — positions / pending orders by magic, sizing          |
//+------------------------------------------------------------------+
#ifndef CORB_ORDERS_MQH
#define CORB_ORDERS_MQH

#include <Trade/Trade.mqh>
#include "Config.mqh"
#include "Guard.mqh"

CTrade g_trade;
datetime g_retryAt = 0; // after a "market closed" reject, no delete/close request before this server time

bool OrdersBackingOff()
  {
   return TimeCurrent() < g_retryAt;
  }

// Market closed: back off a minute instead of resending (and logging) on every tick
string OrdersNoteFailure(const uint retcode)
  {
   if(retcode != TRADE_RETCODE_MARKET_CLOSED)
      return "";
   g_retryAt = TimeCurrent() + 60;
   return " (market closed, retry in 60 s)";
  }

//+------------------------------------------------------------------+
void OrdersInit()
  {
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetAsyncMode(false);
  }

//+------------------------------------------------------------------+
int OrdersCountPositions(const long magic)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == magic)
         n++;
     }
   return n;
  }

// Open time of the oldest position of this magic (0 if none)
datetime OrdersOldestOpenTime(const long magic)
  {
   datetime oldest = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      const datetime t = (datetime)PositionGetInteger(POSITION_TIME);
      if(oldest == 0 || t < oldest)
         oldest = t;
     }
   return oldest;
  }

int OrdersCountPending(const long magic)
  {
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == magic)
         n++;
     }
   return n;
  }

//+------------------------------------------------------------------+
void OrdersDeletePending(const long magic, const string why)
  {
   if(OrdersBackingOff())
      return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol || OrderGetInteger(ORDER_MAGIC) != magic)
         continue;
      if(g_trade.OrderDelete(ticket))
         CorbLog(StringFormat("DELETE order #%I64u magic=%I64d (%s)", ticket, magic, why));
      else
         CorbLog(StringFormat("DELETE FAIL order #%I64u retcode=%u%s", ticket, g_trade.ResultRetcode(),
                              OrdersNoteFailure(g_trade.ResultRetcode())));
     }
  }

void OrdersClosePositions(const long magic, const string why)
  {
   if(OrdersBackingOff())
      return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      if(g_trade.PositionClose(ticket, InpSlippagePoints))
         CorbLog(StringFormat("CLOSE position #%I64u magic=%I64d (%s)", ticket, magic, why));
      else
        {
         CorbLog(StringFormat("CLOSE FAIL position #%I64u retcode=%u%s", ticket, g_trade.ResultRetcode(),
                              OrdersNoteFailure(g_trade.ResultRetcode())));
         if(g_trade.ResultRetcode() == TRADE_RETCODE_MARKET_CLOSED)
            GuardOnCalendarLeak(StringFormat("close of #%I64u refused, market closed (%s)", ticket, why));
        }
     }
  }

void OrdersFlatten(const long magic, const string why)
  {
   OrdersDeletePending(magic, why);
   OrdersClosePositions(magic, why);
  }

//+------------------------------------------------------------------+
double OrdersNormalizePrice(const double price)
  {
   const double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0)
      return NormalizeDouble(price, _Digits);
   return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
  }

// Lots so that a stop-out (plus commission) loses riskMoney. Returns 0 if below min lot.
double OrdersLotForRisk(const bool isBuy, const double entry, const double sl, const double riskMoney)
  {
   if(riskMoney <= 0.0 || entry <= 0.0 || sl <= 0.0)
      return 0.0;

   const double comm = InpCommissionPoints * _Point;
   const double slWithCost = isBuy ? sl - comm : sl + comm;

   double pnl = 0.0;
   if(!OrderCalcProfit(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, 1.0, entry, slWithCost, pnl))
      return 0.0;
   const double lossPerLot = MathAbs(pnl);
   if(lossPerLot <= 0.0)
      return 0.0;

   const double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   const double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   const double maxLot = MathMin(SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX), InpMaxLot);

   double lot = riskMoney / lossPerLot;
   if(step > 0.0)
      lot = MathFloor(lot / step + 1e-9) * step;
   if(lot > maxLot)
      lot = maxLot;
   if(lot < minLot)
      return 0.0;
   return NormalizeDouble(lot, 2);
  }

//+------------------------------------------------------------------+
bool OrdersPlaceStop(const long magic, const bool isBuy, const double lots,
                     const double price, const double sl, const double tp, const string comment)
  {
   g_trade.SetExpertMagicNumber((ulong)magic);
   bool ok;
   if(isBuy)
      ok = g_trade.BuyStop(lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
   else
      ok = g_trade.SellStop(lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);

   CorbLog(StringFormat("%s %s lots=%.2f @%s sl=%s tp=%s magic=%I64d retcode=%u",
                        ok ? "PLACE" : "PLACE FAIL", isBuy ? "BUY_STOP" : "SELL_STOP", lots,
                        DoubleToString(price, _Digits), DoubleToString(sl, _Digits),
                        DoubleToString(tp, _Digits), magic, g_trade.ResultRetcode()));
   return ok;
  }

// True if this magic opened a position since 'from' (restart guard: one trade per day)
bool OrdersEnteredSince(const long magic, const datetime from)
  {
   if(!HistorySelect(from, TimeCurrent() + 60))
      return false;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) == _Symbol
         && HistoryDealGetInteger(deal, DEAL_MAGIC) == magic
         && HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_IN)
         return true;
     }
   return false;
  }

#endif // CORB_ORDERS_MQH
