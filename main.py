"""CLI for data collection and model training; independent from the web server."""
import argparse
import logging
from src.common import RAW, setup
from src.pipeline import run_pipeline

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Processar dados reais Landsat do Recife')
    parser.add_argument('--years',nargs='+',type=int,help='Processar apenas estes anos (substitui os resultados publicados locais)')
    args=parser.parse_args()
    setup()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',
                        handlers=[logging.FileHandler(RAW/'pipeline.log',encoding='utf-8'),logging.StreamHandler()])
    print(run_pipeline(years=args.years))
