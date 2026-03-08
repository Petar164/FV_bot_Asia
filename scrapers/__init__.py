from .mercari_jp import MercariJPScraper
from .yahoo_auctions import YahooAuctionsScraper
from .rakuma import RakumaScraper
from .bunjang import BunjangScraper
from .xianyu import XianyuScraper

__all__ = [
    "MercariJPScraper",
    "YahooAuctionsScraper",
    "RakumaScraper",
    "BunjangScraper",
    "XianyuScraper",
]

# Registry used by main.py to instantiate scrapers by name
SCRAPER_REGISTRY = {
    "mercari_jp": MercariJPScraper,
    "yahoo_auctions": YahooAuctionsScraper,
    "rakuma": RakumaScraper,
    "bunjang": BunjangScraper,
    "xianyu": XianyuScraper,
}
