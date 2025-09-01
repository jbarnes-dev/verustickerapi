#!/usr/bin/env python3
"""
Data Integration Module
Integrates validated data extraction modules with FastAPI
Uses proven working code from all_converters_pairs_working.py and price_inversion.py
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
import sys
import os
from dotenv import load_dotenv

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from block_height import get_session_block_height, clear_session, start_new_session
from price_inversion import apply_universal_price_inversion

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_available_chains() -> List[str]:
    """Get list of available chains from environment variables"""
    chains = []
    for key in os.environ:
        if key.endswith('_BLOCKS_PER_DAY'):
            chain = key.replace('_BLOCKS_PER_DAY', '')
            chains.append(chain)
    return chains

def get_chain_config(chain: str) -> Dict:
    """Get configuration for a specific chain from environment variables"""
    blocks_per_day = int(os.getenv(f"{chain}_BLOCKS_PER_DAY", "1440"))
    block_time_seconds = int(os.getenv(f"{chain}_BLOCK_TIME_SECONDS", "60"))
    name = os.getenv(f"{chain}_NAME", chain)
    
    return {
        "blocks_per_day": blocks_per_day,
        "block_time_seconds": block_time_seconds,
        "name": name
    }

def get_chain_for_converter(converter_name: str) -> str:
    """Determine the target chain for a converter based on its name"""
    # Hardcoded chain mappings for reliability (fallback from .env approach)
    bridge_mappings = {
        'Bridge.vARRR': 'VARRR',
        'Bridge.vDEX': 'VDEX', 
        'Bridge.vCHIPS': 'CHIPS',
        'Bridge.CHIPS': 'CHIPS'
    }
    
    native_mappings = {
        '.CHIPS': 'CHIPS',
        '.VARRR': 'VARRR',
        '.VDEX': 'VDEX'
    }
    
    # Check for exact bridge converter matches first
    if converter_name in bridge_mappings:
        return bridge_mappings[converter_name]
    
    # Check for native chain converters
    for suffix, chain in native_mappings.items():
        if converter_name.endswith(suffix):
            return chain
    
    # Default to VRSC
    return "VRSC"

def get_currency_volume_info(currency, from_block, end_block, interval, volume_currency, target_chain=None, output_file='volume_response.json'):
    """
    Get volume information - using existing working RPC connection
    Copied from validated all_converters_pairs_working.py
    """
    from verus_rpc import make_rpc_call
    
    # Determine correct chain based on converter name if not provided
    if not target_chain:
        target_chain = get_chain_for_converter(currency)
    
    # Get chain configuration from .env
    chain_config = get_chain_config(target_chain)
    if not chain_config:
        return None, None
    
    # Use chain-specific blocks per day instead of hardcoded interval
    chain_blocks_per_day = chain_config.get('blocks_per_day', interval)
    
    # Determine the native currency for the target chain
    native_currencies = {
        "VRSC": "VRSC",
        "CHIPS": "CHIPS", 
        "VARRR": "vARRR",
        "VDEX": "vDEX"
    }
    
    # Use chain's native currency instead of hardcoded volume_currency
    chain_native_currency = native_currencies.get(target_chain, volume_currency)
    
    # Calculate proper block range using chain-specific configuration
    # Get current block height for the target chain
    current_height_result = make_rpc_call(
        chain=target_chain,
        method="getinfo",
        params=[]
    )
    
    if not current_height_result or 'blocks' not in current_height_result:
        return None, None
    
    current_height = current_height_result['blocks']
    calculated_start_block = current_height - chain_blocks_per_day
    calculated_end_block = current_height
    
    # Use consistent RPC call format for all chains (like API_Rebuild_v1_complete)
    block_range_param = f"{calculated_start_block}, {calculated_end_block}, {chain_blocks_per_day}"
    result = make_rpc_call(
        chain=target_chain,
        method="getcurrencystate",
        params=[currency, block_range_param, volume_currency]
    )
    
    # Create response format to match original
    response = {'result': result} if result else None
    
    
    try:
        # Check if the response contains the expected data - restore v1 logic
        if not isinstance(response, dict) or 'result' not in response or not isinstance(response['result'], list):
            return None, None
            
        result = response['result']
        
        # Look for conversion data in the result list - v1 working logic
        conversion_data = None
        total_volume = None
        
        # Find the conversion data and total volume in the result list
        for item in result:
            if isinstance(item, dict):
                if 'conversiondata' in item:
                    conversion_data = item['conversiondata']
                if 'totalvolume' in item:
                    total_volume = item['totalvolume']
        
        # Check if we found the conversion data
        if conversion_data and 'volumepairs' in conversion_data:
            volume_pairs = conversion_data['volumepairs']
            return volume_pairs, total_volume
        else:
            return None, None
    except Exception as e:
        logger.error(f"Error extracting volume data: {e}")
        return None, None

def find_pair_volume(volume_pairs, from_currency, to_currency):
    """Find volume for specific currency pair"""
    if not volume_pairs:
        return 0
    
    for pair in volume_pairs:
        if (pair.get('currency') == from_currency and 
            pair.get('convertto') == to_currency):
            return pair.get('volume', 0)
    
    return 0

def find_pair_ohlc(volume_pairs, from_currency, to_currency):
    """Find OHLC data for specific currency pair"""
    if not volume_pairs:
        return {'open': 0, 'high': 0, 'low': 0, 'close': 0}
    
    for pair in volume_pairs:
        if (pair.get('currency') == from_currency and 
            pair.get('convertto') == to_currency):
            return {
                'open': pair.get('open', 0),
                'high': pair.get('high', 0),
                'low': pair.get('low', 0),
                'close': pair.get('close', 0)
            }
    
    return {'open': 0, 'high': 0, 'low': 0, 'close': 0}

def load_converter_data(multi_chain=False):
    """Load converter discovery data with optional multi-chain support
    
    Args:
        multi_chain (bool): If True, discover converters from all 4 chains
                           If False, use VRSC only (default for backward compatibility)
    
    Returns:
        List of active converter data
    """
    try:
        # Use relative path that works on any server
        discovery_file = os.path.join(os.path.dirname(__file__), 'converter_discovery.json')
        with open(discovery_file, 'r') as f:
            data = json.load(f)
        
        if 'active_converters' in data:
            logger.info(f"Loaded {len(data['active_converters'])} converters from existing discovery file")
            return data['active_converters']
        return []
    except FileNotFoundError:
        logger.warning("converter_discovery.json not found, generating automatically...")
        try:
            # Import and run converter discovery
            import converter_discovery
            import time
            
            # Choose chains based on multi_chain parameter
            if multi_chain:
                chains = ["VRSC", "CHIPS", "VARRR", "VDEX"]
                logger.info("🔍 Auto-generating multi-chain converter discovery data...")
            else:
                chains = ["VRSC"]
                logger.info("🔍 Auto-generating VRSC-only converter discovery data...")
            
            result = converter_discovery.discover_active_converters(chains=chains)
            
            # Wait a moment for file to be written
            time.sleep(1)
            
            # Verify file was created
            discovery_file = os.path.join(os.path.dirname(__file__), 'converter_discovery.json')
            if not os.path.exists(discovery_file):
                logger.error("converter_discovery.json was not created after generation")
                return []
            
            # Try loading again after generation
            with open(discovery_file, 'r') as f:
                data = json.load(f)
            
            if 'active_converters' in data:
                logger.info(f"✅ Auto-generated and loaded {len(data['active_converters'])} converters")
                return data['active_converters']
            else:
                logger.error("Generated file does not contain 'active_converters' key")
                return []
        except Exception as gen_error:
            logger.error(f"Failed to auto-generate converter discovery: {gen_error}")
            return []
    except Exception as e:
        logger.error(f"Error loading converter data: {e}")
        return []

def get_converter_currencies(converter):
    """Extract currencies from a converter for pair analysis"""
    currencies = []
    
    # Add the converter currency itself as a tradeable asset
    converter_name = converter.get('name')
    converter_id = converter.get('currency_id')
    if converter_name:
        currencies.append({
            'symbol': converter_name,
            'currency_id': converter_id or ''
        })
    
    # Add all reserve currency tickers with their IDs
    for reserve in converter.get('reserve_currencies', []):
        if 'ticker' in reserve:
            currencies.append({
                'symbol': reserve['ticker'],
                'currency_id': reserve.get('currency_id', '')
            })
    
    return currencies

def get_converter_currency_symbols(converter):
    """Extract just currency symbols for backward compatibility"""
    currencies = get_converter_currencies(converter)
    return [curr['symbol'] for curr in currencies]

def get_currency_id_by_symbol(currencies, symbol):
    """Get currency ID by symbol from currency list"""
    for curr in currencies:
        if curr['symbol'] == symbol:
            return curr['currency_id']
    return ''

def extract_all_pairs_data(session_id: Optional[str] = None) -> Dict:
    """
    Extract all pairs data across all converters using validated methodology
    
    Args:
        session_id: Optional session ID for block height consistency
    
    Returns:
        Dict containing all pairs data with metadata
    """
    try:
        logger.info("Starting comprehensive pairs data extraction...")
        
        # Start new session if not provided
        if not session_id:
            session_id = start_new_session()
        
        # Get session data
        current_block = get_session_block_height()
        
        # Load existing working converter data with multichain support
        converters = load_converter_data(multi_chain=True)
        
        if not converters:
            logger.error("No converter data found")
            return {
                'error': 'No converter data available',
                'timestamp': datetime.utcnow().isoformat(),
                'pairs': []
            }
        
        logger.info(f"Processing {len(converters)} active converters")
        
        all_pairs = []
        
        # Process each converter using validated methodology
        for converter_idx, converter in enumerate(converters, 1):
            converter_name = converter.get('name', 'Unknown')
            currencies = get_converter_currencies(converter)
            currency_symbols = [curr['symbol'] for curr in currencies]
            
            # Determine target chain and get its configuration
            target_chain = get_chain_for_converter(converter_name)
            chain_config = get_chain_config(target_chain)
            blocks_per_day = chain_config["blocks_per_day"]
            
            # Calculate chain-specific block range
            start_block = current_block - blocks_per_day
            end_block = current_block
            
            logger.info(f"Processing converter {converter_idx}/{len(converters)}: {converter_name}")
            logger.info(f"Using {target_chain} chain with block range: {start_block} to {end_block} ({blocks_per_day} blocks/day)")
            
            if len(currencies) < 2:
                logger.warning(f"Skipping {converter_name} - only {len(currencies)} currencies")
                continue
            
            # Make calls for each currency in this converter (validated 5-call methodology)
            all_volume_data = {}
            
            for currency_info in currencies:
                currency_symbol = currency_info['symbol']
                logger.debug(f"Calling with {currency_symbol} as volume currency for {converter_name}")
                
                volume_pairs, total_volume = get_currency_volume_info(
                    converter_name, start_block, end_block, blocks_per_day, currency_symbol, target_chain
                )
                
                if volume_pairs is not None:
                    all_volume_data[currency_symbol] = {
                        'volume_pairs': volume_pairs,
                        'total_volume': total_volume
                    }
                    logger.debug(f"Got {len(volume_pairs)} pairs for {currency_symbol}")
                else:
                    logger.warning(f"Failed to get volume data for {currency_symbol} in {converter_name}")
            
            # Extract pairs for this converter using validated methodology
            for base_currency in currency_symbols:
                for target_currency in currency_symbols:
                    if base_currency != target_currency:
                        
                        # Get raw base volume (from base currency call)
                        raw_base_volume = 0
                        base_data = all_volume_data.get(base_currency)
                        if base_data:
                            raw_base_volume = find_pair_volume(
                                base_data['volume_pairs'], base_currency, target_currency
                            )
                        
                        # Get raw target volume (from target currency call)
                        # Use same direction as v1: base_currency -> target_currency
                        raw_target_volume = 0
                        target_data = all_volume_data.get(target_currency)
                        if target_data:
                            raw_target_volume = find_pair_volume(
                                target_data['volume_pairs'], base_currency, target_currency
                            )
                        
                        # Get OHLC data (from target currency call for consistency)
                        ohlc_data = {'open': 0, 'high': 0, 'low': 0, 'close': 0}
                        if target_data:
                            ohlc_data = find_pair_ohlc(
                                target_data['volume_pairs'], base_currency, target_currency
                            )
                        
                        # Calculate base and target volumes using corrected methodology
                        # Base volume = raw volume from base currency call
                        # Target volume = raw volume from target currency call
                        calculated_base_volume = raw_base_volume
                        calculated_target_volume = raw_target_volume
                        
                        # Only include pairs with volume
                        if calculated_base_volume > 0 or calculated_target_volume > 0:
                            # Get currency IDs for enhanced mapping
                            base_currency_id = get_currency_id_by_symbol(currencies, base_currency)
                            target_currency_id = get_currency_id_by_symbol(currencies, target_currency)
                            
                            # Calculate liquidity during data extraction
                            from liquidity_calculator import get_pair_liquidity
                            pair_liquidity_usd = get_pair_liquidity(converter_name, base_currency, target_currency, converters)
                            
                            pair_data = {
                                'converter': converter_name,
                                'base_currency': base_currency,
                                'target_currency': target_currency,
                                'base_currency_id': base_currency_id,
                                'target_currency_id': target_currency_id,
                                'symbol': f"{base_currency}-{target_currency}",
                                'base_volume': calculated_base_volume,
                                'target_volume': calculated_target_volume,
                                'base_volume_24h': calculated_base_volume,
                                'target_volume_24h': calculated_target_volume,
                                'last_price': ohlc_data['close'],
                                'open': ohlc_data['open'],
                                'high': ohlc_data['high'],
                                'low': ohlc_data['low'],
                                'last': ohlc_data['close'],
                                'raw_base_volume': raw_base_volume,
                                'raw_target_volume': raw_target_volume,
                                'pair_liquidity_usd': pair_liquidity_usd,
                                'has_volume': True
                            }
                            
                            # Apply universal price inversion to convert blockchain rates to trading pair rates
                            inverted_pair_data = apply_universal_price_inversion(pair_data)
                            
                            all_pairs.append(inverted_pair_data)
        
        result = {
            'success': True,
            'timestamp': datetime.utcnow().isoformat(),
            'session_id': session_id,
            'block_range': {
                'start': 'chain-specific',
                'end': current_block,
                'current': current_block,
                'interval': 'chain-specific'
            },
            'total_converters': len(converters),
            'total_pairs': len(all_pairs),
            'pairs': all_pairs,
            'session_block_height': current_block
        }
            
        logger.info(f"Successfully extracted {len(all_pairs)} pairs from {len(converters)} converters")
        return result
        
    except Exception as e:
        logger.error(f"Error in extract_all_pairs_data: {str(e)}")
        return {
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat(),
            'pairs': []
        }

def get_ticker_data(format_type: str = "raw") -> Dict:
    """
    Get ticker data in specified format
    
    Args:
        format_type: "raw", "coingecko", or "verus_statistics"
    
    Returns:
        Dict containing ticker data
    """
    try:
        # Extract all pairs data
        data = extract_all_pairs_data()
        
        if 'error' in data:
            return data
        
        if format_type == "raw":
            return data
        elif format_type == "coingecko":
            # Will be implemented in Subtask 3
            return {
                'error': 'CoinGecko format not yet implemented',
                'raw_data_available': True,
                'pairs_count': len(data.get('pairs', []))
            }
        elif format_type == "verus_statistics":
            # Will be implemented in Subtask 3
            return {
                'error': 'Verus Statistics format not yet implemented',
                'raw_data_available': True,
                'pairs_count': len(data.get('pairs', []))
            }
        else:
            return {
                'error': f'Unknown format type: {format_type}',
                'available_formats': ['raw', 'coingecko', 'verus_statistics']
            }
            
    except Exception as e:
        logger.error(f"Error in get_ticker_data: {str(e)}")
        return {
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }

def test_data_integration():
    """Test the data integration module"""
    print("🧪 Testing Data Integration Module")
    print("=" * 50)
    
    try:
        # Test raw data extraction
        print("1. Testing raw data extraction...")
        raw_data = get_ticker_data("raw")
        
        if 'error' in raw_data:
            print(f"   ❌ Error: {raw_data['error']}")
            return False
        
        pairs_count = len(raw_data.get('pairs', []))
        print(f"   ✅ Successfully extracted {pairs_count} pairs")
        print(f"   📊 Block range: {raw_data['block_range']['start']} to {raw_data['block_range']['end']}")
        print(f"   🏦 Converters: {raw_data['total_converters']}")
        
        # Show sample pairs
        if pairs_count > 0:
            print("\n2. Sample pairs:")
            for i, pair in enumerate(raw_data['pairs'][:3]):  # Show first 3
                print(f"   {i+1}. {pair['symbol']} ({pair['converter']})")
                print(f"      Base Volume: {pair['base_volume']:,.2f} {pair['target_currency']}")
                print(f"      Target Volume: {pair['target_volume']:,.2f} {pair['base_currency']}")
                print(f"      Last Price: {pair['last']:.8f}")
                print(f"      Inverted: {pair.get('inverted', False)}")
        
        print("\n✅ Data integration test completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Data integration test failed: {str(e)}")
        return False
    
    finally:
        # Clean up session
        clear_session()

if __name__ == "__main__":
    test_data_integration()
