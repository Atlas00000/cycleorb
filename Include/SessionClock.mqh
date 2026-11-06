//+------------------------------------------------------------------+
//| SessionClock.mqh — server / UTC / London / New York / Tokyo        |
//+------------------------------------------------------------------+
#ifndef CORB_SESSIONCLOCK_MQH
#define CORB_SESSIONCLOCK_MQH

#include "Config.mqh"

enum ENUM_CORB_ZONE
  {
   CORB_ZONE_LONDON  = 0,
   CORB_ZONE_NEWYORK = 1,
   CORB_ZONE_TOKYO   = 2  // JST = UTC+9 all year (no DST)
  };

//+------------------------------------------------------------------+
datetime ClockMakeDate(const int year, const int month, const int day)
  {
   MqlDateTime t;
   ZeroMemory(t);
   t.year = year;
   t.mon  = month;
   t.day  = day;
   return StructToTime(t);
  }

int ClockYear(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.year;
  }

int ClockDayOfWeek(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.day_of_week;
  }

datetime ClockDayStart(const datetime t)
  {
   return t - (t % 86400);
  }

// n-th Sunday (n >= 1) of a month, 00:00
datetime ClockNthSunday(const int year, const int month, const int n)
  {
   const datetime first = ClockMakeDate(year, month, 1);
   const int add = (7 - ClockDayOfWeek(first)) % 7;
   return first + (add + 7 * (n - 1)) * 86400;
  }

// Last Sunday of a month, 00:00
datetime ClockLastSunday(const int year, const int month)
  {
   const datetime next = (month == 12) ? ClockMakeDate(year + 1, 1, 1)
                                       : ClockMakeDate(year, month + 1, 1);
   const datetime last = next - 86400;
   return last - ClockDayOfWeek(last) * 86400;
  }

// UK: last Sunday of March 01:00 UTC to last Sunday of October 01:00 UTC
bool ClockIsUKDST(const datetime utc)
  {
   const int y = ClockYear(utc);
   return (utc >= ClockLastSunday(y, 3) + 3600 && utc < ClockLastSunday(y, 10) + 3600);
  }

// US: 2nd Sunday of March 07:00 UTC to 1st Sunday of November 06:00 UTC
bool ClockIsUSDST(const datetime utc)
  {
   const int y = ClockYear(utc);
   return (utc >= ClockNthSunday(y, 3, 2) + 7 * 3600 && utc < ClockNthSunday(y, 11, 1) + 6 * 3600);
  }

//+------------------------------------------------------------------+
int ClockServerOffsetSec(const datetime utc)
  {
   if(InpServerTZ == CORB_TZ_FIXED)
      return InpServerFixedOffsetH * 3600;
   return (ClockIsUSDST(utc) ? 3 : 2) * 3600;
  }

datetime ClockServerToUtc(const datetime server)
  {
   return server - ClockServerOffsetSec(server - 2 * 3600);
  }

datetime ClockUtcToServer(const datetime utc)
  {
   return utc + ClockServerOffsetSec(utc);
  }

int ClockZoneOffsetSec(const ENUM_CORB_ZONE zone, const datetime utc)
  {
   if(zone == CORB_ZONE_LONDON)
      return ClockIsUKDST(utc) ? 3600 : 0;
   if(zone == CORB_ZONE_TOKYO)
      return 9 * 3600;
   return ClockIsUSDST(utc) ? -4 * 3600 : -5 * 3600;
  }

datetime ClockUtcToLocal(const ENUM_CORB_ZONE zone, const datetime utc)
  {
   return utc + ClockZoneOffsetSec(zone, utc);
  }

datetime ClockLocalToServer(const ENUM_CORB_ZONE zone, const datetime local)
  {
   const int stdOffset = (zone == CORB_ZONE_LONDON) ? 0 : (zone == CORB_ZONE_TOKYO ? 9 * 3600 : -5 * 3600);
   const datetime utc = local - ClockZoneOffsetSec(zone, local - stdOffset);
   return ClockUtcToServer(utc);
  }

//+------------------------------------------------------------------+
// Broker trade session open at server time 'now'. A symbol without any session table counts as open.
bool ClockTradeSessionOpen(const datetime now)
  {
   const ENUM_DAY_OF_WEEK dow = (ENUM_DAY_OF_WEEK)ClockDayOfWeek(now);
   const int sec = (int)(now % 86400);
   datetime from, to;
   bool any = false;
   for(uint i = 0; SymbolInfoSessionTrade(_Symbol, dow, i, from, to); i++)
     {
      any = true;
      const bool wraps = ((int)to <= (int)from);
      if(wraps ? (sec >= (int)from || sec < (int)to) : (sec >= (int)from && sec < (int)to))
         return true;
     }
   if(any)
      return false;
   for(int d = 0; d < 7; d++)
      if(SymbolInfoSessionTrade(_Symbol, (ENUM_DAY_OF_WEEK)d, 0, from, to))
         return false;
   return true;
  }

// Live only: detected server offset differs from the configured one (always false in the tester)
bool ClockMismatch()
  {
   if(MQLInfoInteger(MQL_TESTER))
      return false;
   const int detected = (int)MathRound((double)(TimeTradeServer() - TimeGMT()) / 3600.0);
   return detected != ClockServerOffsetSec(TimeGMT()) / 3600;
  }

//+------------------------------------------------------------------+
void ClockLogInfo()
  {
   const datetime now = TimeCurrent();
   const int y = ClockYear(now);
   CorbLog(StringFormat("Clock %d: UK DST %s -> %s | US DST %s -> %s | server offset now %+dh",
                        y,
                        TimeToString(ClockLastSunday(y, 3), TIME_DATE),
                        TimeToString(ClockLastSunday(y, 10), TIME_DATE),
                        TimeToString(ClockNthSunday(y, 3, 2), TIME_DATE),
                        TimeToString(ClockNthSunday(y, 11, 1), TIME_DATE),
                        ClockServerOffsetSec(ClockServerToUtc(now)) / 3600));

   if(MQLInfoInteger(MQL_TESTER))
      return;

   const int detected = (int)MathRound((double)(TimeTradeServer() - TimeGMT()) / 3600.0);
   const int expected = ClockServerOffsetSec(TimeGMT()) / 3600;
   if(detected != expected)
      CorbLog(StringFormat("WARNING server offset mismatch: detected %+dh, configured %+dh — check InpServerTZ",
                           detected, expected));
  }

#endif // CORB_SESSIONCLOCK_MQH
