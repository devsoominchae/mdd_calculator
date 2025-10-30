### Max Drawdown (MDD) Calculator
This is a Python app built with tkinter to calculate current drawdown and a recovery ratio. The recovery ratio is calculated as (number of days with drawdown higher than today) / (number of total days after IPO) so that we can "buy the dip". 

For example, VOO's historical MDD is around -34%. At that value, the recovery ratio is 99.97% and we can bet to "buy the dip".

To use this tool, add the tickers you would like to analyze to the tickers.txt file. Then run 
######
    python mdd.py

You can set how often the stock price gets updated or refresh instantly.
