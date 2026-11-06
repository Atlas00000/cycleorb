//+------------------------------------------------------------------+
//| Events.mqh — static high-impact calendar for AI OS features (L1)   |
//| File: Common\Files\CycleORB\events.csv, written by the script      |
//| Scripts\CycleORB\CycleORB_ExportCalendar (the MT5 calendar is not  |
//| available in the Strategy Tester). Columns:                        |
//| server_time,currency,importance,name                               |
//+------------------------------------------------------------------+
#ifndef CORB_EVENTS_MQH
#define CORB_EVENTS_MQH

#include "Config.mqh"

#define CORB_EVENTS_FILE "CycleORB\\events.csv"

datetime g_evTime[];
string   g_evName[];
bool     g_evLoaded = false;

bool EventsCcyWanted(const string ccy)
  {
   return StringFind("," + InpAosEventCcy + ",", "," + ccy + ",") >= 0;
  }

void EventsLoad()
  {
   ArrayResize(g_evTime, 0);
   ArrayResize(g_evName, 0);
   g_evLoaded = false;
   const int h = FileOpen(CORB_EVENTS_FILE, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
     {
      CorbLog("AOS events file missing: Common\\Files\\" + CORB_EVENTS_FILE + " (event features left empty)");
      return;
     }
   while(!FileIsEnding(h))
     {
      string f[];
      if(StringSplit(FileReadString(h), ',', f) < 4 || f[2] != "HIGH" || !EventsCcyWanted(f[1]))
         continue;
      const datetime t = StringToTime(f[0]);
      if(t <= 0)
         continue;
      const int k = ArraySize(g_evTime);
      ArrayResize(g_evTime, k + 1);
      ArrayResize(g_evName, k + 1);
      g_evTime[k] = t;
      g_evName[k] = f[1] + " " + f[3];
     }
   FileClose(h);
   g_evLoaded = true;
   CorbLog(StringFormat("AOS events loaded: %d high-impact (%s)", ArraySize(g_evTime), InpAosEventCcy));
  }

// High-impact events with from <= time < to
int EventsCount(const datetime from, const datetime to)
  {
   int n = 0;
   for(int i = 0; i < ArraySize(g_evTime); i++)
      if(g_evTime[i] >= from && g_evTime[i] < to)
         n++;
   return n;
  }

// Minutes from 'from' to the next event within horizonMin, -1 if none
int EventsMinutesToNext(const datetime from, const int horizonMin)
  {
   int best = -1;
   for(int i = 0; i < ArraySize(g_evTime); i++)
     {
      const long dt = (long)(g_evTime[i] - from);
      if(dt >= 0 && dt < horizonMin * 60L && (best < 0 || dt / 60 < best))
         best = (int)(dt / 60);
     }
   return best;
  }

string EventsFirst(const datetime from, const datetime to)
  {
   datetime bestT = 0;
   string name = "";
   for(int i = 0; i < ArraySize(g_evTime); i++)
      if(g_evTime[i] >= from && g_evTime[i] < to && (bestT == 0 || g_evTime[i] < bestT))
        {
         bestT = g_evTime[i];
         name = g_evName[i];
        }
   return name;
  }

#endif // CORB_EVENTS_MQH
