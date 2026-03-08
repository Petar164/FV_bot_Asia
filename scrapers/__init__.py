from .mercari_jp import MercariJPScraper
from .yahoo_auctions import YahooAuctionsScraper
from .rakuma import RakumaScraper
from .bunjang import BunjangScraper
from .xianyu import XianyuScraper
from .vinted import VintedScraper
from .vestiaire import VestiaireScraper

__all__ = [
    "MercariJPScraper",
    "YahooAuctionsScraper",
    "RakumaScraper",
    "BunjangScraper",
    "XianyuScraper",
    "VintedScraper",
    "VestiaireScraper",
]

# Registry used by main.py to instantiate scrapers by name
SCRAPER_REGISTRY = {
    "mercari_jp":     MercariJPScraper,
    "yahoo_auctions": YahooAuctionsScraper,
    "rakuma":         RakumaScraper,
    "bunjang":        BunjangScraper,
    "xianyu":         XianyuScraper,
    "vinted":         VintedScraper,
    "vestiaire":      VestiaireScraper,
}
