import datetime
import time
from exchange.oanda import Oanda
from logic.candle import Candle
from logic import movingaverage
from logic import MarketTrend
from logic.risk import RiskManager
from logic.timestop import TimeStop
import logging
import traceback

class Strategy(object):

    SHORT_EMA_PERIOD = 50
    LONG_EMA_PERIOD = 200

    def __init__(self, oanda, candle_size = 120, email = None, risk = 2):
        self._oanda = oanda
        self._oanda.SubscribeTicker(self)
        self._current_candle = None
        self._candle_size = candle_size
        self._risk = RiskManager(oanda, risk)
        self._email = email
        self._short_ema = movingaverage.ExponentialMovingAverage(Strategy.SHORT_EMA_PERIOD)
        self._long_ema = movingaverage.ExponentialMovingAverage(Strategy.LONG_EMA_PERIOD)
        self._timestop = TimeStop()
        self._logging_current_price = 0.0
        self.trading_enabled = False
        self._tp = 0.00035
        self.takeProfit = 0.0

    def Start(self):
        logging.info("Starting strategy")
        #self._catchTradeException("---","email test")
        # Prefeed the strategy with historic candles
        candle_count = self._long_ema.AmountOfDataStillMissing() + 1
        Candles = self._oanda.GetCandles(candle_count, self._candle_size)
        for c in Candles:
            self._short_ema.Update(c)
            self._long_ema.Update(c)
        self._oanda.StartPriceStreaming()
        self.trading_enabled = True

    def PauseTrading(self):
        logging.info("Pausing strategy")
        self.trading_enabled = False

    def ResumeTrading(self):
        logging.info("Resuming strategy")
        self.trading_enabled = True

    def TradingStatus(self):
        return self.trading_enabled

    def SetTradingStatus(self, tstatus):
        self.trading_enabled = tstatus

    def Stop(self):
        logging.info("Stop strategy")
        self.SetTradingStatus(False)
        self._oanda.StopPriceStreaming()

    def Update(self, datapoint):
        logging.info("StrategyUpdate")
        if not isinstance(datapoint, Candle):
            if not self._current_candle:
                openTime = datapoint["now"]
                closeTime = datapoint["now"] + datetime.timedelta(minutes=self._candle_size)
                logging.info("close time test---- put 0300-0330 here")
                logging.info(closeTime)
                self._current_candle = Candle(openTime, closeTime)
            else:
                self._current_candle.Update(datapoint)
                #update July 8 2019
                #round(datapoint["value"],5) fix for invalid precicion error in oanda.py
            self._logging_current_price = round(datapoint["value"],5)#format(datapoint["value"], '.5f')
        else:
            self._current_candle = datapoint
            self._logging_current_price = round(datapoint.Close, 5)

        # Check if it is Friday night and we should seize trading
        self._timestop.Update(datapoint)
        _state = self._timestop.GetState()
        if _state == MarketTrend.STOP_LONG or _state == MarketTrend.STOP_SHORT:
            if (self._oanda.CurrentPosition() > 0):
                logging.info("Timing Stop fired, TGIF!: "+str(_state) + " price: "+ str(self._logging_current_price))
                self.ClosePosition()
                return

        if not self._current_candle.SeenEnoughData():
            return

        self._short_ema.Update(self._current_candle)
        self._long_ema.Update(self._current_candle)

        self._current_candle = None

        logging.info("Price: " + str(round(self._logging_current_price,5)))
        logging.info("Long EMA: " + str(round(self._long_ema.value,5)))
        logging.info("short EMA: " + str(round(self._short_ema.value,5)))
        logging.info("TP Price LONG: " + str(round(self._logging_current_price + self._tp,5)))
        logging.info("TP Price SHORT: " + str(round(self._logging_current_price - self._tp,5)))

        #Take Profit
        if (self._logging_current_price > self.takeProfit):
            self.ClosePosition()

        #localtime = time.localtime(time.time())
        #if (localtime.tm_hour-4 == 3 and localtime.tm_min < 31):
        if (self._logging_current_price > self._short_ema.value):
            logging.info("PRICE ABOVE EMA STRATEGY TEST")
            if (self._oanda.CurrentPosition() > 0):
            #if (self._oanda.CurrentPosition() > 0) and (self._oanda.CurrentPositionSide == MarketTrend.ENTER_SHORT):
                return
            else:
                logging.info("PRICE ABOVE EMA STRATEGY TEST")
                #self.ClosePosition()
                #self.Sell()

        #strategy being used
        if (self._logging_current_price < self._short_ema.value):
            logging.info("PRICE BELOW EMA STRATEGY TEST")
            logging.info(self._current_candle)
            #Check if current position is open
            if (self._oanda.CurrentPosition() > 0):
        #if (self._short_ema.value > self._long_ema.value):
            #if (self._oanda.CurrentPosition() > 0) and (self._oanda.CurrentPositionSide == MarketTrend.ENTER_LONG):
                return
            else:
                self.ClosePosition()
                self.Buy()



        #if (self._long_ema.value > self._short_ema.value):
            #if (self._oanda.CurrentPosition() > 0) and (self._oanda.CurrentPositionSide == MarketTrend.ENTER_SHORT):
                #return
            #else:
                #self.ClosePosition()
                #self.Sell()




    def Buy(self):

        logging.info("Strategy Buy() called. Going long @ " + str(self._logging_current_price))

        #backtest take profit
        self.takeProfit = round(self._logging_current_price + self._tp,5)

        if not self.trading_enabled:
            logging.info("Strategy trading disabled, doing nothing")
            return

        # Enter the long position on the instrument
        units = self._risk.GetLongPositionSize()

        logging.info("Got the number of units to trade from RiskManager: "+str(units)+" with a TP position of: "+str(self._logging_current_price+self._tp))
        if units == 0:
            logging.info("Cant trade zero units, doing nothing")
            return

        try:
            #self.takeProfit = round(self._logging_current_price + self._tp,5)
            logging.info("takeProfit: " +str(self.takeProfit))
            self._oanda.Buy(units, self.takeProfit)
        except Exception as e:
            self._catchTradeException(e,"enter long")

    def Sell(self):

        logging.info("Strategy Sell() called. Going short @ " + str(self._logging_current_price))
        if not self.trading_enabled:
            logging.info("Trading disabled, doing nothing")
            return

        # Enter the short position on the instrument
        units = self._risk.GetShortPositionSize()
        #tp=.0015
        logging.info("Got the number of units to trade from RiskManager: "+str(units)+" with a TP position of: "+str(self._logging_current_price+.0015))
        if units == 0:
            logging.info("Cant trade 0 units, doing nothing")
            return

        try:
            self._oanda.Sell(units, takeProfit)
        except Exception as e:
            self._catchTradeException(e,"enter short")

    def ClosePosition(self):

        logging.info("Closing position, and all stops")
        if not self.trading_enabled:
            logging.info("Trading disabled, doing nothing")
            return


        try:
            self._oanda.ClosePosition()
        except Exception as e:
            self._catchTradeException(e,"close")

    def GetStopLossPrice(self):
        return 0.0

    def GetTrailingStopPrice(self):
        return 0.0

    def _catchTradeException(self, e, position):
            logging.critical("Failed to "+position+" position")
            logging.critical(traceback.format_exc())
            if self._email:
                txt = "\n\nError while trying to "+position+" position\n"
                txt += "It was caught, I should still be running\n\n"
                txt += traceback.format_exc()+"\n"+str(e)
                self._email.Send(txt)
