"""Synthetic local pricing and budget fixture; never a production default."""
import json
PRICE={'version':'synthetic-v1','model':'deepseek-flash','currency':'USD','input_cache_hit_per_million':'0.02','input_cache_miss_per_million':'0.5','output_per_million':'2'}
ENV={'DEEPSEEK_PRICING_JSON':json.dumps(PRICE),'DEEPSEEK_MODEL':'deepseek-flash'}
