from logger import getLogger
from logger import LevelsByName

CRIT = LevelsByName.CRIT
ERRO = LevelsByName.ERRO
WARN = LevelsByName.WARN
INFO = LevelsByName.INFO
DEBG = LevelsByName.DEBG
TRAC = LevelsByName.TRAC
BLAT = LevelsByName.BLAT

__all__ = ['CRIT', 'ERRO', 'WARN', 'INFO', 'DEBG', 'TRAC', 'BLAT', 'getLogger']
