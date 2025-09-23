#!/usr/bin/env python3
"""
Liquidity Calculator Module
Implements pair liquidity calculation using proven working code from Deploy
Formula: Pair Liquidity = Total Converter Liquidity × (Weight of Currency A + Weight of Currency B)
"""

import json
import logging
from typing import Dict, Optional
import sys
import os

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from verus_rpc import make_rpc_call
from dict import get_ticker_by_id
from block_height import get_session_block_height

logger = logging.getLogger(__name__)

# Session-based cache for VRSC USD price (like API_v8)
_vrsc_usd_cache = {}

def get_vrsc_usd_price_cached():
    """
    Get VRSC to USD price using vETH conversion via NATI🦉 + ETH price
    Uses session-based caching for consistency (same pattern as API_v8)
    """
    try:
        # Get current session ID for caching
        session_id = get_session_block_height()
        
        # Check if we have cached price for this session
        if session_id in _vrsc_usd_cache:
            logger.info(f"Using cached VRSC USD price for session {session_id}: ${_vrsc_usd_cache[session_id]}")
            return _vrsc_usd_cache[session_id]
        
        # Step 1: Convert VRSC to vETH via NATI🦉
        conversion_params = {'currency': 'VRSC', 'convertto': 'vETH', 'amount': 1, 'via': 'NATI🦉'}
        result = make_rpc_call('VRSC', 'estimateconversion', [conversion_params])
        
        if not result or 'estimatedcurrencyout' not in result:
            return 0.0
            
        vrsc_veth_rate = float(result['estimatedcurrencyout'])
        
        # Step 2: Get ETH price with fallback (import from currency_price_cache)
        try:
            from currency_price_cache import get_eth_price_with_fallback
            eth_usd_price = get_eth_price_with_fallback()
        except ImportError:
            # Fallback if import fails
            eth_usd_price = 0.0
        
        if eth_usd_price <= 0:
            return 0.0
            
        # Step 3: Calculate VRSC USD price
        vrsc_usd_price = vrsc_veth_rate * eth_usd_price
        
        # Cache the result for this session
        _vrsc_usd_cache[session_id] = vrsc_usd_price
        logger.info(f"Cached VRSC USD price for session {session_id}: ${vrsc_usd_price}")
        
        return vrsc_usd_price
        
    except Exception as e:
        logger.error(f"Error getting VRSC→USD price: {e}")
        return 0.0

def get_chain_to_vrsc_rate(chain: str) -> float:
    """
    Get conversion rate from any chain's native currency to VRSC via bridge
    Standardized function for multi-chain support
    
    Args:
        chain: Chain name (CHIPS, VARRR, VDEX, etc.)
        
    Returns:
        Conversion rate (native currency to VRSC)
    """
    try:
        # Determine bridge name based on chain
        if chain == 'CHIPS':
            bridge_name = 'Bridge.CHIPS'
        elif chain == 'VARRR':
            bridge_name = 'Bridge.vARRR'
        elif chain == 'VDEX':
            bridge_name = 'Bridge.vDEX'
        else:
            # Standard naming convention for future chains
            bridge_name = f'Bridge.{chain}'
        
        # Get native currency to VRSC conversion via bridge
        conversion_params = {'currency': chain, 'convertto': 'VRSC', 'amount': 1, 'via': bridge_name}
        conversion_result = make_rpc_call(chain, 'estimateconversion', [conversion_params])
        
        if conversion_result and 'estimatedcurrencyout' in conversion_result:
            rate = float(conversion_result['estimatedcurrencyout'])
            logger.info(f"Got {chain}→VRSC rate via {bridge_name}: {rate}")
            return rate
        else:
            logger.error(f"Failed to get {chain}→VRSC conversion via {bridge_name}")
            return 0.0
            
    except Exception as e:
        logger.error(f"Error getting {chain}→VRSC conversion: {e}")
        return 0.0

def get_chain_usd_price(chain: str) -> float:
    """
    Get USD price for any chain's native currency
    Standardized multi-step conversion: Chain → VRSC → USD
    
    Args:
        chain: Chain name (CHIPS, VARRR, VDEX, etc.)
        
    Returns:
        USD price per native currency unit
    """
    try:
        # Step 1: Get chain to VRSC rate
        chain_to_vrsc_rate = get_chain_to_vrsc_rate(chain)
        
        if chain_to_vrsc_rate <= 0:
            return 0.0
        
        # Step 2: Get VRSC to USD price
        vrsc_usd_price = get_vrsc_usd_price_cached()
        
        if vrsc_usd_price <= 0:
            return 0.0
        
        # Step 3: Calculate chain USD price
        chain_usd_price = chain_to_vrsc_rate * vrsc_usd_price
        logger.info(f"Calculated {chain} USD price: {chain_usd_price} (rate: {chain_to_vrsc_rate} × VRSC: {vrsc_usd_price})")
        
        return chain_usd_price
        
    except Exception as e:
        logger.error(f"Error calculating {chain} USD price: {e}")
        return 0.0

def get_converter_liquidity(converter_name: str, converters_data: Dict, min_liquidity_threshold: float = 1000.0) -> float:
    """
    Calculate total liquidity for a converter in USD
    Based on proven working code from Deploy/batch_api_v2.py with multi-chain support
    
    Args:
        converter_name: Name of the converter
        converters_data: Converter discovery data
        min_liquidity_threshold: Minimum liquidity threshold in native currency (default: 1000)
        
    Returns:
        Total liquidity in USD (0 if below threshold)
    """
    try:
        # Find the converter in the data
        converter_info = None
        for conv in converters_data:
            if conv.get('name') == converter_name:
                converter_info = conv
                break
        
        if not converter_info:
            logger.error(f"Converter {converter_name} not found in data")
            return 0.0
        
        converter_id = converter_info.get('currency_id')
        supply = float(converter_info.get('supply', 0))
        
        if not converter_id or supply <= 0:
            logger.error(f"Invalid converter ID or supply for {converter_name}")
            return 0.0
        
        # Step 1: Get converter to native chain currency conversion ratio
        source_chain = converter_info.get('source_chain', 'VRSC')
        native_ratio = 0
        
        # Special handling for Bridge converters on VARRR and VDEX chains
        if source_chain in ['VARRR', 'VDEX'] and converter_name.startswith('Bridge.'):
            # Use proper converter-to-native-chain conversion method
            native_currency = source_chain  # vARRR or vDEX
            try:
                conversion_params = {'currency': converter_id, 'convertto': native_currency, 'amount': 1}
                conversion_result = make_rpc_call(source_chain, 'estimateconversion', [conversion_params])
                
                if conversion_result and 'estimatedcurrencyout' in conversion_result:
                    native_ratio = float(conversion_result['estimatedcurrencyout'])
                    logger.info(f"Got {converter_name} to {native_currency} ratio: {native_ratio}")
            except Exception as e:
                logger.error(f"Error getting {converter_name} to {native_currency} conversion: {e}")
        
        elif source_chain == 'VRSC':
            # VRSC converters - convert to VRSC
            try:
                conversion_params = {'currency': converter_id, 'convertto': 'VRSC', 'amount': 1}
                conversion_result = make_rpc_call('VRSC', 'estimateconversion', [conversion_params])
                
                if conversion_result and 'estimatedcurrencyout' in conversion_result:
                    native_ratio = float(conversion_result['estimatedcurrencyout'])
            except Exception as e:
                logger.error(f"Error getting {converter_name} to VRSC conversion: {e}")
        else:
            # Other chains - native converters
            # Get converter-to-native-chain ratio (e.g., Highroller.CHIPS -> CHIPS)
            native_currency = source_chain  # CHIPS, VARRR, VDEX
            try:
                conversion_params = {'currency': converter_id, 'convertto': native_currency, 'amount': 1}
                conversion_result = make_rpc_call(source_chain, 'estimateconversion', [conversion_params])
                
                if conversion_result and 'estimatedcurrencyout' in conversion_result:
                    native_ratio = float(conversion_result['estimatedcurrencyout'])
                    logger.info(f"Got {converter_name} to {native_currency} ratio: {native_ratio}")
            except Exception as e:
                logger.error(f"Error getting {converter_name} to {native_currency} conversion: {e}")
        
        if native_ratio <= 0:
            logger.error(f"Could not get valid native currency ratio for {converter_name}")
            return 0.0
        
        # Step 2: Get native currency to USD price
        if source_chain == 'VRSC':
            # VRSC converters - use direct VRSC to USD price
            native_usd_price = get_vrsc_usd_price_cached()
        else:
            # All other chains (CHIPS, VARRR, VDEX) - use standardized multi-step conversion
            native_usd_price = get_chain_usd_price(source_chain)
        
        if native_usd_price <= 0:
            logger.error(f"Could not get valid {source_chain}→USD price")
            return 0.0
        
        # Step 3: Calculate total liquidity = supply × native_ratio × native_USD_price
        total_liquidity = supply * native_ratio * native_usd_price
        
        # Apply minimum liquidity threshold
        if supply < min_liquidity_threshold:
            logger.info(f"Converter {converter_name} below threshold: {supply} < {min_liquidity_threshold}")
            return 0.0
        
        logger.info(f"Liquidity calculation for {converter_name} (Chain: {source_chain}):")
        logger.info(f"  Supply: {supply}")
        logger.info(f"  Native ratio: {native_ratio}")
        logger.info(f"  Native USD price: {native_usd_price}")
        logger.info(f"  Total liquidity: ${total_liquidity:.2f}")
        
        return total_liquidity
        
    except Exception as e:
        logger.error(f"Error calculating converter liquidity for {converter_name}: {e}")
        return 0.0

def get_pair_liquidity(converter_name: str, base_currency: str, target_currency: str, converters_data: Dict) -> float:
    """
    Calculate the liquidity for a specific trading pair in a converter
    Formula: (weight1 + weight2) / total_weight * total_liquidity
    Based on proven working code from Deploy/batch_api_v2.py
    
    Args:
        converter_name: Name of the converter
        base_currency: Base currency of the pair
        target_currency: Target currency of the pair
        converters_data: Converter discovery data
        
    Returns:
        Pair liquidity in USD
    """
    try:
        # Get total converter liquidity first
        total_liquidity = get_converter_liquidity(converter_name, converters_data)
        
        if total_liquidity <= 0:
            return 0.0
        
        # Find the converter in the data
        converter_info = None
        for conv in converters_data:
            if conv.get('name') == converter_name:
                converter_info = conv
                break
        
        if not converter_info:
            logger.error(f"Converter {converter_name} not found in data")
            return 0.0
        
        # Get weights for the currencies
        base_weight = 0
        target_weight = 0
        total_weight = 0
        
        reserve_currencies = converter_info.get('reserve_currencies', [])
        for rc in reserve_currencies:
            weight = float(rc.get('weight', 0))
            total_weight += weight
            
            currency_ticker = rc.get('ticker', '')
            
            if currency_ticker == base_currency:
                base_weight = weight
            if currency_ticker == target_currency:
                target_weight = weight
        
        # Check if this is a special case (converter currency is one of the pair currencies)
        base_is_converter = (base_currency == converter_name)
        target_is_converter = (target_currency == converter_name)
        is_special_case = base_is_converter or target_is_converter
        
        if is_special_case:
            # Special case: one currency is the converter itself
            # Find the weight of the non-converter currency
            non_converter_weight = target_weight if base_is_converter else base_weight
            
            if non_converter_weight > 0 and total_weight > 0:
                # Formula: (weight * total_liquidity) * 2
                weight_fraction = non_converter_weight / total_weight
                pair_liquidity = (weight_fraction * total_liquidity) * 2
                return pair_liquidity
            else:
                return 0.0
        else:
            # Regular case: both currencies are reserve currencies
            if base_weight > 0 and target_weight > 0 and total_weight > 0:
                # Formula: (weight1 + weight2) / total_weight * total_liquidity
                combined_weight_fraction = (base_weight + target_weight) / total_weight
                pair_liquidity = combined_weight_fraction * total_liquidity
                return pair_liquidity
            else:
                return 0.0
                
    except Exception as e:
        logger.error(f"Error calculating pair liquidity for {base_currency}-{target_currency} in {converter_name}: {e}")
        return 0.0

def test_liquidity_calculator():
    """Test the liquidity calculator with Bridge.vETH"""
    try:
        from data_integration import load_converter_data
        
        print("🧪 Testing Liquidity Calculator")
        print("=" * 50)
        
        # Load converter data
        converters_data = load_converter_data()
        if not converters_data:
            print("❌ No converter data available")
            return
        
        # Test with Bridge.vETH
        converter_name = "Bridge.vETH"
        
        # Test total converter liquidity
        total_liquidity = get_converter_liquidity(converter_name, converters_data)
        print(f"✅ Total {converter_name} liquidity: ${total_liquidity:.2f}")
        
        # Test pair liquidity for VRSC-DAI.vETH
        pair_liquidity = get_pair_liquidity(converter_name, "VRSC", "DAI.vETH", converters_data)
        print(f"✅ VRSC-DAI.vETH pair liquidity: ${pair_liquidity:.2f}")
        
        print("\n✅ Liquidity calculator test completed!")
        
    except Exception as e:
        print(f"❌ Error in liquidity calculator test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_liquidity_calculator()
