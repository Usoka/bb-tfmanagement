from .tfmanagement import TFManagement
import os

DATA_DIR = 'data/boombeach'

def ensure_dirs():
	if not os.path.exists(DATA_DIR):
		os.makedirs(DATA_DIR)

def setup(bot):
	ensure_dirs()
	bot.add_cog(TFManagement(bot))