# wrapper around oanda's RESTful api
import datetime
import re
import time
import threading
import Queue
import v20
import json
import logging
import traceback

from oandapyV20 import API
#from oandapyV20.contrib.factories import InstrumentsCandlesFactory
import oandapyV20.endpoints.trades as trades
#import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as _instruments
#import oandapyV20.endpoints.positions as positions
#import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.orders as orders
#from oandapyV20.contrib.factories import InstrumentsCandlesFactory
import oandapyV20.types as tp
from exchange import oandapy
from exchange import oandapyV2 as _oa
from logic.candle import Candle
from math import floor
from logic import MarketTrend
from util.watchdog import WatchDog

#from exchange.oanda_api_v20.oandapyV20 import API
#import oandapyV20.endpoints.trades as trades

class OandaPriceStreamer(oandapy.Streamer):
    def __init__(self,environment,api_key,account_id,instrument):
        self._api_key = api_key
        self._account_id = account_id
        self._instrument = instrument
        oandapy.Streamer.__init__(self,environment=environment,access_token=api_key)
        self.ticker_subscribers = []
        self.heartbeat_subscribers = []
        self.updates_subscribers = []
        self.update_necessary = True
        self._queue = Queue.Queue()
        self._thread = threading.Thread(target=OandaPriceStreamer._start,
                                       args=(self,)
                                       )
        self._thread.setDaemon(True)
        self._watchdog = WatchDog()

    def SubscribeTicker(self, obj):
        self.ticker_subscribers.append(obj)

    def SubscribeHeartbeat(self, obj):
        self.heartbeat_subscribers.append(obj)

    def SubscribeUpdates(self, obj):
        self.updates_subscribers.append(obj)

    def IsRunning(self):
        return self._thread.isAlive()

    def _start(self):
        self.start(accountId=self._account_id,instruments=self._instrument,ignore_heartbeat=False)

    def _stop(self):
        self.disconnect()

    def Start(self):
        self._watchdog.Start()
        self._thread.start()

    def Stop(self):
        self._watchdog.Stop()
        self._stop()
        self._thread.join()

    def on_success(self, data):
        self._watchdog.Reset()
        self._queue.put(data)

    def UpdateSubscribers(self):
        # If watchdog fired, throw!
        if self._watchdog.IsExpired():
            txt = "Watchdog: have not seen heartbeat from exchange for "
            txt += str(self._watchdog.watchdog_timeout_seconds) + " seconds"
            raise Exception(txt)

        data = None

        try:
            data = self._queue.get(True, 0.1)
        except:
            return

        if not data:
            return

        if self.update_necessary:
            for obj in self.updates_subscribers:
                obj.Update(None)
            self.update_necessary = False

        if "heartbeat" in data:
            for obj in self.heartbeat_subscribers:
                obj.Update(data["heartbeat"])
            return

        if "tick" not in data:
            return

        ask = float(data["tick"]["ask"])
        bid = float(data["tick"]["bid"])
        ts = time.mktime(time.strptime(data["tick"]["time"], '%Y-%m-%dT%H:%M:%S.%fZ'))
        #'%Y-%m-%dT%H:%M:%S.%fZ'
        price = (ask + bid) / 2.0

        datapoint = {}
        datapoint["now"] = datetime.datetime.fromtimestamp(ts)
        datapoint["value"] = price
        for obj in self.ticker_subscribers:
            obj.Update(datapoint)

        return True


class Oanda(object):
    def __init__(self, api_key, account_id,  access_tokenv20, accountIDv20, instrument, home_base_pair, HOSTNAME, account_currency, DATETIME_FORMAT,  home_base_default_exchange_rate = 1.0, environment="practice",email=None):
        self._api_key = api_key
        self._account_id = account_id
        self.access_tokenv20=access_tokenv20
        self.accountIDv20 = accountIDv20
        self._instrument = instrument
        self._home_base_pair = home_base_pair
        self.hostname=HOSTNAME
        self._account_currency = account_currency
        self._home_base_default_exchange_rate = home_base_default_exchange_rate
        self._email = email
        self.tradeIDs=0
        #Depreciated
        self._oanda = oandapy.API(environment=environment,access_token=self._api_key)
        #
        self._oanda_price_streamer = OandaPriceStreamer(environment=environment,
                                                        api_key=self._api_key,
                                                        account_id=account_id,
                                                        instrument=instrument
                                                        )
        #v20
        #self._apiv20 = v20.Context( hostname='api-fxpractice.oanda.com', token=self.access_tokenv20, datetime_format=DATETIME_FORMAT)
        self._oandav20 = API(environment="practice", access_token="6a30d839d3b1f05d75d2ed6b035829b5-1cfc0b66be9b95ae9bb2fcf41b45c1d7")
        #self.accountID = self.accountIDv20
        self.trades=trades
        self.orders=orders
        self._instruments=_instruments
        self._oanda__ = _oa#.APIV20(environment=environment,api_key=self._api_key,account_id=account_id, instrument=instrument)

    def SubscribeTicker(self, obj):
        self._oanda_price_streamer.SubscribeTicker(obj)

    def SubscribeHeartbeat(self, obj):
        self._oanda_price_streamer.SubscribeHeartbeat(obj)

    def SubscribeUpdates(self, obj):
        self._oanda_price_streamer.SubscribeUpdates(obj)

    def StartPriceStreaming(self):
        self._oanda_price_streamer.Start()

    def StopPriceStreaming(self):
        self._oanda_price_streamer.Stop()

    def GetNetWorth(self):
        try:
            logging.info("GetNetWorth")
            response=self._oanda__.get_accounts(self)
            logging.info("RESPONSE:\n{}".format(json.dumps(response, indent=2)))

            if "id" in response['account']["trades"]:
                logging.info("There's an ID")
                self.tradeIDs =  response['account']['trades'][0]['id']
                logging.info(self.tradeIDs)
            else:
                logging.info("There's NO ID")
            #self.tradeIDs =  response.get(['account']['trades'][0]['id'], None)
            #logging.info(self.tradeIDs)

        except Exception as ex:
            self._oanda_price_streamer.update_necessary = True
            self._catchTradeException(ex,"GetNetWorth")
            return 0.0
        return float(response["account"]["balance"])

    def GetBalance(self):
        retValue = {}
        netWorth = self.GetNetWorth()
        retValue[self._account_currency] = netWorth

        try:
            logging.info("GetBalance")
            logging.info(netWorth)
            response = self._oanda__.open_trades(self)
            logging.info("GetBalance RESPONSE:\n{}".format(json.dumps(response, indent=2)))
        except:
            self._oanda_price_streamer.update_necessary = True
            return retValue

        if not response or not response["trades"]:
            return retValue

        for item in response["trades"]:
            retValue[item["instrument"]] = float(item["currentUnits"])

        return retValue

    def CashInvested(self):
        try:
            logging.info("CashInvested")
            response = self._oanda__.open_trades(self)
            #logging.info("RESPONSE:\n{}".format(json.dumps(response, indent=2)))
            marginUsed = float(response["trades"][0]["marginUsed"])
            return marginUsed
        except:
            return 0.0

    def CurrentPosition(self):
        try:
            logging.info("CurrentPosition")
            response = self._oanda__.open_trades(self)
            return int(response["trades"][0]["currentUnits"])
        except:
            self._oanda_price_streamer.update_necessary = True
            return 0

    def Leverage(self):
        try:
            logging.info("Leverage")
            response=self._oanda__.get_accounts(self)
        except:
            self._oanda_price_streamer.update_necessary = True
            return 0.0
        margin_rate = float(response["account"]["marginRate"])
        leverage = 1.0 / margin_rate
        return leverage

    def UnrealizedPNL(self):
        try:
            logging.info("UnrealizedPNL")
            response = self._oanda__.get_accounts(self)
        except:
            self._oanda_price_streamer.update_necessary = True
            return 0.0
        return float(response['account']['unrealizedPL'])

    def CurrentPositionSide(self):
        try:
            logging.info("CurrentPositionSide")
            response = self._oanda__.get_position(self)
            logging.info("CurrentPositionSide RESPONSE:\n{}".format(json.dumps(response, indent=2)))
            logging.info(response["position"]["long"]["tradeIDs"][0])
            if response["position"]["long"]["tradeIDs"][0] > 0 :
                logging.info("MarketTrend.ENTER_LONG")
                return MarketTrend.ENTER_LONG
            if response["position"]["short"]["tradeIDs"][0] > 0:
                logging.info("MarketTrend.ENTER_SHORT")
                return MarketTrend.ENTER_SHORT

        except:
            self._oanda_price_streamer.update_necessary = True
            return MarketTrend.NONE

    def AvailableUnits(self):
        logging.info("AvailableUnits")
        exchange_rate = self._home_base_default_exchange_rate
        params = {"instruments":self._instrument}
        logging.info(params)
        try:
            response = self._oanda__.get_pricing(self,params)
            #logging.info("RESPONSE:\n{}".format(json.dumps(response, indent=2)))
            exchange_rate =( float(response['prices'][0]['bids'][0]['price']) + float(response['prices'][0]['asks'][0]['price']) ) / 2.0
        except:
            pass
        try:
            response=self._oanda__.get_accounts(self)
            margin_available = float(response["account"]["marginAvailable"])
            margin_rate = float(response["account"]["marginRate"])
            leverage = 1.0 / margin_rate
            return int(floor( margin_available * leverage / exchange_rate ))
        except:
            self._oanda_price_streamer.update_necessary = True
            return 0
#>>>> need v20 conversion
    def Sell(self, units, takeProfit):
        self._oanda.create_order(self._account_id,
                                 instrument=self._instrument,
                                 units=units,
                                 side='sell',
                                 type='market',
                                 takeProfit=takeProfit
                                )
        self._oanda_price_streamer.update_necessary = True
#>>>> takeProfit doesnt work
    def Buy(self, units, takeProfit):
        logging.info("Buy")
        data={
              "order": {
                #"price": "1.5000",
                #"stopLossOnFill": {
                  #"timeInForce": "GTC",
                  #"price": "0.0000"
                #},
                "takeProfitOnFill": {
                  "price": round(takeProfit,5)
                },
                "timeInForce": "FOK",
                "instrument": self._instrument,
                "units": units,
                "type": "MARKET",
                "positionFill": "DEFAULT",
                "clientID":"@opyTESTorders"
              }
            }

        response_v20=self.orders.OrderCreate(self.accountIDv20,data=data)
        response = self._oandav20.request(response_v20)
        self._oanda_price_streamer.update_necessary = True
        logging.info("BUY RESPONSE:\n{}".format(json.dumps(response, indent=2)))
        self.email("Buy", response)

    def ClosePosition(self):
        logging.info("ClosePosition")
        data={"units":"ALL"}

        response=self._oanda__.get_accounts(self)
        logging.info("RESPONSE:\n{}".format(json.dumps(response, indent=2)))

        #test if there's an tradeID to close
        if "id" in response['account']["trades"]:

            self.tradeIDs =  response['account']['trades'][0]['id']
            logging.info("There's an ID" + str(self.tradeIDs))


            self.close_v20= self.trades.TradeClose(accountID=self.accountIDv20,tradeID=self.tradeIDs,data=data)
            response = self._oandav20.request(self.close_v20)
            logging.info("ClosePosition RESPONSE:\n{}".format(json.dumps(response, indent=2)))

        else:
            logging.info("There's NO ID")

    def GetCandles(self, number_of_last_candles_to_get = 0, size_of_candles_in_minutes = 120):
        logging.info("GetCandles")
        Candles = []

        if number_of_last_candles_to_get <= 0 or size_of_candles_in_minutes <= 0:
            return Candles

        _granularity = self._getGranularity(size_of_candles_in_minutes)
        #response = self._oanda.get_history(instrument=self._instrument,
                                #granularity=_granularity,
                                #count=number_of_last_candles_to_get + 1,
                                #candleFormat="midpoint"
                                #)
        params={
                "granularity":_granularity,
                "count":number_of_last_candles_to_get + 1,
                "price":"M"

                }

        self.GetCandles_v20 = self._instruments.InstrumentsCandles(
                                instrument=self._instrument,
                                params=params
                                )
        response = self._oandav20.request(self.GetCandles_v20)

        if not response.has_key("candles"):
            return Candles

        for item in response["candles"]:
            if item["complete"] != True:
                continue
            _item = item['time'].replace('000', '', 1)#V20
            close_ts = datetime.datetime.fromtimestamp(
                        time.mktime(time.strptime(str(_item), '%Y-%m-%dT%H:%M:%S.%fZ')))
            open_ts = close_ts - datetime.timedelta(minutes = size_of_candles_in_minutes)
            c = Candle(open_ts, close_ts)

            #c.Open  = item["openMid"]
            #c.High  = item["highMid"]
            #c.Low   = item["lowMid"]
            #c.Close = item["closeMid"]

            c.Open  = item["mid"]["o"],
            c.High  = item["mid"]["h"]
            c.Low   = item["mid"]["l"]
            c.Close   = item["mid"]["c"]

            c._is_closed = True
            Candles.append(c)
            #logging.info("CANDLES:\n{}".format(json.dumps(response, indent=2)))
        self._oanda_price_streamer.update_necessary = True

        return sorted(Candles, key = lambda candle: candle.CloseTime)

    def IsRunning(self):
        return self._oanda_price_streamer.IsRunning()

    def UpdateSubscribers(self):
        self._oanda_price_streamer.UpdateSubscribers()

    # Dont care about candles that are smaller then one minute
    # Only a few supported. See details here:
    # http://developer.oanda.com/rest-live/rates/#retrieveInstrumentHistory
    def _getGranularity(self, size_in_minutes):
        if size_in_minutes == 2:
            return "M2"
        elif size_in_minutes == 3:
            return "M3"
        elif size_in_minutes == 4:
            return "M4"
        elif size_in_minutes == 5:
            return "M5"
        elif size_in_minutes == 10:
            return "M10"
        elif size_in_minutes == 15:
            return "M15"
        elif size_in_minutes == 30:
            return "M30"
        elif size_in_minutes == 60:
            return "H1"
        elif size_in_minutes == 120:
            return "H2"
        elif size_in_minutes == 240:
            return "H4"
        elif size_in_minutes == 480:
            return "H8"
        elif size_in_minutes == 1440:
            return "D1"
        # default: two hour candles
        return "H2"

    def _catchTradeException(self, ex, position):
        logging.critical("Exception from "+position)
        logging.critical(traceback.format_exc())
        if self._email:
            txt = "\n\nError while trying to "+position+" position\n"
            txt += "It was caught, I should still be running\n\n"
            txt += traceback.format_exc()+"\n"+str(ex)
            self._email.Send(txt)

    def email(position,response):
        if self._email:
            txt = "\n\n!!U P D A T E!!\n"
            txt += position+" order has been placed \n\n"
            txt += response
            self._email.Send(txt)


def OandaExceptionCode(exception):
    if not exception:
        return 0
    match = re.match("OANDA API returned error code ([0-9]+)\s.*", str(exception))
    if not match:
        return 1
    return match.group(1)
