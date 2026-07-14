#!/usr/bin/env python3
"""
Verus Ticker API - FastAPI Implementation
Core FastAPI skeleton with basic structure and health checks
"""

import os
import logging
import sys
import json
import subprocess
import signal
import time
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from verussupply import get_vrsc_supply
from dotenv import load_dotenv
import uvicorn

# Load environment variables
load_dotenv()

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Check if live endpoints should be enabled
ENABLE_LIVE_ENDPOINTS = os.getenv('ENABLE_LIVE_ENDPOINTS', 'false').lower() == 'true'
logger.info(f"Live endpoints enabled: {ENABLE_LIVE_ENDPOINTS}")

# Create FastAPI app with pretty JSON formatting
app = FastAPI(
    title="Verus Ticker API v4",
    description="Real-time cryptocurrency ticker data from Verus blockchain (optimized)",
    version="4.0.0",
    docs_url=None,
    redoc_url=None
)

# Configure JSON formatting for human readability
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as BaseJSONResponse

class PrettyJSONResponse(BaseJSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            jsonable_encoder(content),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            separators=(',', ': ')
        ).encode('utf-8')

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception on {request.url}: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# VRSC supply endpoint already imported above

@app.get("/verussupply")
async def verussupply_endpoint():
    """Get VRSC supply information including total supply, VRSC in converters, and circulating supply"""
    return await get_vrsc_supply()

# Favicon endpoint to prevent 404 errors
@app.get("/favicon.ico")
async def favicon():
    """Return empty response for favicon to prevent 404 errors"""
    return Response(content="", media_type="image/x-icon")

# Combined health check and cache status endpoint
@app.get("/health")
async def health_and_cache_status():
    """
    Combined health check and cache status endpoint
    
    Returns:
        Server health, RPC connection status, cache information, and performance metrics
    """
    try:
        from cache_manager import get_cache_status
        from verus_rpc import make_rpc_call
        
        # Test RPC connection
        rpc_status = "ok"
        current_block = 0
        try:
            result = make_rpc_call("VRSC", "getinfo", [])
            if result and 'blocks' in result:
                current_block = result.get('blocks', 0)
            else:
                rpc_status = "failed"
        except Exception as rpc_e:
            rpc_status = f"error: {str(rpc_e)}"
        
        # Get cache information
        cache_info = get_cache_status()
        
        # Prepare comprehensive response
        response_data = {
            "status": "healthy" if rpc_status == "ok" else "degraded",
            "rpc_connection": rpc_status,
            "current_block": current_block,
            "version": "1.0.0",
            "cache_status": cache_info,
            "endpoints": {
                "cached": [
                    "/coingecko",
                    "/verus/market",
                    "/coinmarketcap",
                    "/coinpaprika",
                    "/coinmarketcap_iaddress"
                ],
                "non_cached": [
                    "/coingecko_live",
                    "/coinmarketcap_live",
                    "/coinpaprika_live",
                    "/coinmarketcap_iaddress_live"
                ],
                "utility": [
                    "/verussupply"
                ]
            },
            "performance_benefits": {
                "cached_response_time": "<0.1s (typical)",
                "non_cached_response_time": "0.5-1.0s (typical)",
                "rpc_calls_saved": "60-80 calls per cached request"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        pretty_json = json.dumps(response_data, indent=2, ensure_ascii=False)
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"❌ Error in health endpoint: {e}")
        error_json = json.dumps({"error": str(e), "status": "unhealthy"}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=503
        )

# Root endpoint
@app.get("/", response_class=HTMLResponse)
async def root():
    """Verus Ticker API Documentation - Complete Endpoint Reference"""
    with open('templates/index.html', 'r') as f:
        f = f.readlines()
    html_content = ''.join(f).replace("{{base_url}}", os.environ['BASE_URL'])
    return HTMLResponse(content=html_content)

# API v1 router placeholder (unused endpoint removed)

# Multi-chain converter discovery endpoint
@app.get("/converters")
async def get_converters(chain: str = None):
    """
    Get converter discovery data with optional chain filtering
    
    Args:
        chain: Optional chain filter (VRSC, CHIPS, VARRR, VDEX). If not specified, returns all chains.
    """
    try:
        from converter_discovery import discover_active_converters
        from block_height import start_new_session, clear_session
        
        logger.info(f"Processing converter discovery request for chain: {chain or 'all chains'}")
        
        # Start new session for consistency
        session_id = start_new_session()
        
        try:
            # Determine which chains to discover
            if chain:
                # Validate chain parameter
                valid_chains = ["VRSC", "CHIPS", "VARRR", "VDEX"]
                if chain.upper() not in valid_chains:
                    return PrettyJSONResponse(
                        content={"error": f"Invalid chain '{chain}'. Valid chains: {valid_chains}"},
                        status_code=400
                    )
                chains = [chain.upper()]
            else:
                # Discover all chains
                chains = ["VRSC", "CHIPS", "VARRR", "VDEX"]
            
            # Discover converters
            result = discover_active_converters(chains=chains, save_results=False)
            
            if 'error' in result:
                logger.error(f"Converter discovery failed: {result['error']}")
                return PrettyJSONResponse(
                    content={"error": result['error']},
                    status_code=503
                )
            
            logger.info(f"Successfully discovered {result['active_count']} converters across {len(chains)} chains")
            return PrettyJSONResponse(content=result)
            
        finally:
            # Clean up session
            clear_session()
        
    except Exception as e:
        logger.error(f"Error in converter discovery endpoint: {str(e)}")
        return PrettyJSONResponse(
            content={"error": "Internal server error"},
            status_code=500
        )

# ============================================================================
# LIVE ENDPOINTS (DISABLED BY DEFAULT - SET ENABLE_LIVE_ENDPOINTS=true TO ENABLE)
# ============================================================================
# These endpoints make fresh RPC calls and are slower but more accurate.
# Use cached endpoints for production. Enable these only for testing/debugging.

if ENABLE_LIVE_ENDPOINTS:
    logger.info("🔴 Live endpoints are ENABLED - these make fresh RPC calls")
else:
    logger.info("✅ Live endpoints are DISABLED - use cached endpoints for production")

if ENABLE_LIVE_ENDPOINTS:
    # Live endpoints implementation
    @app.get("/coingecko_live")
    async def get_coingecko_live():
        """Live CoinGecko endpoint - makes fresh RPC calls"""
        try:
            from data_integration import extract_all_pairs_data
            from ticker_formatting import generate_coingecko_tickers
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = generate_coingecko_tickers(pairs_list, use_cache=False)
            return PrettyJSONResponse(content=tickers_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": "Internal server error"}, status_code=500)
    
    @app.get("/coinmarketcap_live") 
    async def get_coinmarketcap_live():
        """Live CoinMarketCap endpoint - makes fresh RPC calls"""
        try:
            from data_integration import extract_all_pairs_data
            from ticker_formatting import generate_coinmarketcap_enhanced_tickers
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = generate_coinmarketcap_enhanced_tickers(pairs_list)
            return PrettyJSONResponse(content=tickers_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": "Internal server error"}, status_code=500)
    
    @app.get("/coinpaprika_live")
    async def get_coinpaprika_live():
        """Live Coinpaprika endpoint - makes fresh RPC calls"""
        try:
            from data_integration import extract_all_pairs_data
            from ticker_formatting import generate_coinpaprika_tickers
            import time
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = generate_coinpaprika_tickers(pairs_list)
            
            # Wrap in VerusStatisticsAPI format to match v1
            response_data = {
                "code": "200000",
                "data": {
                    "time": int(time.time() * 1000),  # Current timestamp in milliseconds
                    "ticker": tickers_data
                }
            }
            
            return PrettyJSONResponse(content=response_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": "Internal server error"}, status_code=500)
    
    @app.get("/coinmarketcap_iaddress_live")
    async def get_coinmarketcap_iaddress_live():
        """Live CMC I-Address endpoint - makes fresh RPC calls"""
        try:
            from data_integration import extract_all_pairs_data
            from ticker_formatting import format_iaddress_coinmarketcap_tickers
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = format_iaddress_coinmarketcap_tickers(pairs_list)
            return PrettyJSONResponse(content=tickers_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": "Internal server error"}, status_code=500)
else:
    # Disabled endpoints - return informative error messages
    @app.get("/coingecko_live")
    async def get_coingecko_disabled():
        return PrettyJSONResponse(
            content={
                "error": "Live endpoints are disabled",
                "message": "This endpoint makes fresh RPC calls and is disabled for production use",
                "alternatives": {
                    "cached_endpoint": "/coingecko",
                    "description": "Use the cached version for production - 60x faster response times"
                },
                "enable_instructions": "Set ENABLE_LIVE_ENDPOINTS=true in .env file to enable live endpoints"
            },
            status_code=503
        )
    
    @app.get("/coinmarketcap_live")
    async def get_coinmarketcap_disabled():
        return PrettyJSONResponse(
            content={
                "error": "Live endpoints are disabled",
                "message": "This endpoint makes fresh RPC calls and is disabled for production use",
                "alternatives": {
                    "cached_endpoint": "/coinmarketcap",
                    "description": "Use the cached version for production - 60x faster response times"
                },
                "enable_instructions": "Set ENABLE_LIVE_ENDPOINTS=true in .env file to enable live endpoints"
            },
            status_code=503
        )
    
    @app.get("/coinpaprika_live")
    async def get_coinpaprika_disabled():
        return PrettyJSONResponse(
            content={
                "error": "Live endpoints are disabled",
                "message": "This endpoint makes fresh RPC calls and is disabled for production use",
                "alternatives": {
                    "cached_endpoint": "/coinpaprika",
                    "description": "Use the cached version for production - 60x faster response times"
                },
                "enable_instructions": "Set ENABLE_LIVE_ENDPOINTS=true in .env file to enable live endpoints"
            },
            status_code=503
        )
    
    @app.get("/coinmarketcap_iaddress_live")
    async def get_coinmarketcap_iaddress_disabled():
        return PrettyJSONResponse(
            content={
                "error": "Live endpoints are disabled",
                "message": "This endpoint makes fresh RPC calls and is disabled for production use",
                "alternatives": {
                    "cached_endpoint": "/coinmarketcap_iaddress",
                    "description": "Use the cached version for production - 60x faster response times"
                },
                "enable_instructions": "Set ENABLE_LIVE_ENDPOINTS=true in .env file to enable live endpoints"
            },
            status_code=503
        )

def kill_process_on_port(port):
    """Kill any process running on the specified port"""
    try:
        # Find process using the port
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True
        )
        
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    print(f"Killing process {pid} on port {port}")
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1)
                    # Force kill if still running
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            print(f"Cleared port {port}")
        else:
            print(f"Port {port} is free")
    except Exception as e:
        print(f"Error checking/clearing port {port}: {e}")

# ============================================================================
# CACHED ENDPOINTS - Performance optimized versions with unified caching
# ============================================================================

@app.get("/coingecko")
async def get_coingecko_tickers_cached():
    """
    Get all tickers in CoinGecko format (CACHED VERSION)
    
    Features:
    - Unified caching reduces RPC calls
    - Shared data across all cached endpoints
    - Cache info included in response
    - Significantly faster response times
    
    Returns:
        Array of ticker objects in CoinGecko format with cache information
    """
    try:
        from ticker_formatting import generate_coingecko_tickers
        from cache_manager import get_cached_pairs_data_only, get_cache_status
        
        logger.info("🚀 CoinGecko cached endpoint called")
        
        # Get cached pairs data
        raw_data = get_cached_pairs_data_only()
        
        if 'error' in raw_data:
            logger.error(f"Error getting cached data: {raw_data['error']}")
            error_json = json.dumps({"error": "No cached data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        pairs_data = raw_data.get('pairs', [])
        
        # Generate CoinGecko tickers using cache mode
        tickers = generate_coingecko_tickers(pairs_data, use_cache=True)
        
        if not tickers:
            logger.error("No CoinGecko tickers available")
            error_json = json.dumps({"error": "No ticker data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        cache_info = get_cache_status()
        logger.info(f"✅ Returning {len(tickers)} CoinGecko tickers (cached, age: {cache_info.get('age_seconds', 0)}s)")
        
        # Return pure CoinGecko format without any metadata for standard compliance
        # Cache info is available via /cache_status endpoint for monitoring
        
        # Convert to pretty-printed JSON
        pretty_json = json.dumps(tickers, indent=2, ensure_ascii=False)
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"❌ Error in coingecko_cached endpoint: {e}")
        error_json = json.dumps({"error": "Internal server error"}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

@app.get("/verus/market")
async def get_verus_market():
    """
    Native market endpoint for the Verus Explorer.
    Returns all converters, pairs, and currency prices in a single structured response.
    No new RPC calls — reuses 60s cached data.
    """
    try:
        from cache_manager import get_cached_pairs_data_only
        from native_format import format_native_market_data

        logger.info("Native /verus/market endpoint called")

        raw_data = get_cached_pairs_data_only()

        if 'error' in raw_data:
            logger.error(f"Error getting cached data: {raw_data['error']}")
            error_json = json.dumps({"error": "No cached data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )

        result = format_native_market_data(raw_data, filter_basket_pairs=False)

        pretty_json = json.dumps(result, indent=2, ensure_ascii=False)
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    except Exception as e:
        logger.error(f"Error in /verus/market endpoint: {e}")
        error_json = json.dumps({"error": "Internal server error"}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

@app.get("/coinmarketcap")
async def get_cmc_summary_cached():
    """
    Get enhanced ticker data in CoinMarketCap (CMC) DEX format (CACHED VERSION)
    
    Features:
    - Unified caching reduces RPC calls
    - Ethereum contract symbols and addresses
    - Composite keys preserve all pairs
    - Cache info included in response
    - Significantly faster response times
    
    Returns:
        Object with composite keys containing enhanced ticker data with Ethereum contract details
    """
    try:
        from ticker_formatting import generate_coinmarketcap_enhanced_tickers
        from cache_manager import get_cached_pairs_data_only, get_cache_status
        
        logger.info("🚀 Enhanced CMC DEX cached endpoint called")
        
        # Get cached pairs data
        raw_data = get_cached_pairs_data_only()
        
        if 'error' in raw_data:
            logger.error(f"Error getting cached data: {raw_data['error']}")
            error_json = json.dumps({"error": "No cached data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        pairs_data = raw_data.get('pairs', [])
        
        # Generate enhanced CMC tickers using cache mode
        enhanced_tickers = generate_coinmarketcap_enhanced_tickers(pairs_data, use_cache=True)
        
        if not enhanced_tickers:
            logger.error("No enhanced CMC tickers available")
            error_json = json.dumps({"error": "No ticker data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        cache_info = get_cache_status()
        logger.info(f"✅ Returning {len(enhanced_tickers)} enhanced CMC DEX tickers (cached, age: {cache_info.get('age_seconds', 0)}s)")
        
        # Return pure CMC format without any cache metadata for standard compliance
        # Cache info is available via /cache_status endpoint for monitoring
        
        # Convert to pretty-printed JSON
        pretty_json = json.dumps(enhanced_tickers, indent=2, ensure_ascii=False)
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"❌ Error in coinmarketcap_cached endpoint: {e}")
        error_json = json.dumps({"error": "Internal server error"}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )




# ============================================================================
# VERUS STATISTICS API COMPATIBLE ENDPOINT
# ============================================================================

@app.get("/coinpaprika")
async def get_coinpaprika():
    """
    Coinpaprika endpoint - VerusStatisticsAPI compatible format
    ==========================================================
    
    Provides data in the same format as https://marketapi.verus.services/market/allTickers
    but uses our existing reliable data source with:
    - ERC20 symbols from currency_contract_mapping
    - Same-pair aggregation (NO inverse pair aggregation)
    - Proper exclusion of converter currencies and excluded chains
    - Volume-weighted price aggregation
    
    Returns:
        JSON array of ticker objects with ERC20 symbols
    """
    try:
        from ticker_formatting import generate_coinpaprika_tickers
        from cache_manager import get_cached_pairs_data_only
        
        logger.info("🚀 Coinpaprika endpoint called")
        
        # Get cached pairs data (no RPC calls)
        pairs_data = get_cached_pairs_data_only()
        
        if 'error' in pairs_data:
            logger.error(f"Error extracting pairs data: {pairs_data['error']}")
            error_json = json.dumps({"error": "Failed to extract trading pairs data"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        pairs_list = pairs_data.get('pairs', [])
        
        # Generate allTickers response
        tickers = generate_coinpaprika_tickers(pairs_list, use_cache=False)
        
        if not tickers:
            logger.error("No ticker data available for coinpaprika")
            # Return empty response in VerusStatisticsAPI format
            empty_response = {
                "code": "200000",
                "data": {
                    "time": int(time.time() * 1000),  # Current timestamp in milliseconds
                    "ticker": []
                }
            }
            empty_json = json.dumps(empty_response, indent=2)
            return Response(
                content=empty_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        # Return tickers in VerusStatisticsAPI format
        response_data = {
            "code": "200000",
            "data": {
                "time": int(time.time() * 1000),  # Current timestamp in milliseconds
                "ticker": tickers
            }
        }
        
        response_json = json.dumps(response_data, indent=2)
        logger.info(f"✅ Coinpaprika: returning {len(tickers)} tickers")
        
        return Response(
            content=response_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        import traceback
        logger.error(f"❌ Error in Coinpaprika endpoint: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return Response(
            content="[]",
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )


@app.get("/coinmarketcap_iaddress")
async def get_coinmarketcap_iaddress():
    """
    CoinMarketCap I-Address Format - TESTING ENDPOINT
    ===============================================
    
    CoinMarketCap-style endpoint using i-addresses as keys instead of ERC20 contract addresses.
    This is a separate implementation for testing purposes.
    
    Key Differences from /coinmarketcap:
    - Uses i-addresses (currency IDs) as base_id and quote_id
    - Uses i-address composite keys instead of contract address keys
    - Maintains same aggregation logic and format structure
    - Separate formatter to avoid modifying existing endpoint
    
    Format: CoinMarketCap DEX API compatible
    Keys: Sequential numbers ("0", "1", "2", etc.)
    Aggregation: Same-pair aggregation with volume-weighted pricing
    
    Response Format:
    {
      "0": {
        "base_id": "i5w5MuNik5NtLcYmNzcvaoixooEebB6MGV",
        "base_name": "VRSC",
        "base_symbol": "VRSC",
        "quote_id": "iGBs4DWztRNvNEJBt4mqHszLxfKTNHTkhM",
        "quote_name": "DAI.vETH",
        "quote_symbol": "DAI.vETH",
        "last_price": "0.46750232",
        "base_volume": "13151.93791997",
        "quote_volume": "27972.04617264"
      }
    }
    """
    try:
        from ticker_formatting import format_iaddress_coinmarketcap_tickers
        from cache_manager import get_cached_pairs_data_only
        
        logger.info("🔍 Processing I-Address CoinMarketCap endpoint request")
        
        # Get cached pairs data (no RPC calls)
        pairs_response = get_cached_pairs_data_only()
        
        if 'error' in pairs_response or not pairs_response.get('pairs'):
            logger.error("No cached pairs data available for I-Address CMC endpoint")
            error_json = json.dumps({"error": "No ticker data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        # Extract the actual pairs data from the response
        pairs_data = pairs_response['pairs']
        
        # Format tickers using i-address formatter
        formatted_tickers = format_iaddress_coinmarketcap_tickers(pairs_data, use_cache=False)
        
        if not formatted_tickers:
            logger.error("No I-Address CMC tickers generated")
            error_json = json.dumps({"error": "No ticker data available"}, indent=2)
            return Response(
                content=error_json,
                media_type="application/json",
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        
        logger.info(f"✅ Returning {len(formatted_tickers)} I-Address CMC tickers")
        
        # Convert to pretty-printed JSON
        pretty_json = json.dumps(formatted_tickers, indent=2, ensure_ascii=False)
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"❌ Error in I-Address CMC endpoint: {e}")
        error_json = json.dumps({"error": "Internal server error"}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )


@app.get("/validate")
async def validate_endpoints():
    """
    Comprehensive API Endpoint Validation
    ====================================
    
    Runs automated validation checks on all API endpoints:
    1. Scientific notation detection
    2. Pair count validation 
    3. Cached vs non-cached endpoint matching
    4. Volume aggregation verification
    5. Data consistency checks
    
    Returns:
        JSON response with detailed validation results
    """
    try:
        from validation_endpoint import run_validation
        
        logger.info("🔍 API Validation endpoint called")
        
        # Run comprehensive validation
        validation_results = run_validation()
        
        # Custom JSON serialization to prevent scientific notation
        def decimal_serializer(obj):
            if isinstance(obj, float):
                return f"{obj:.8f}"
            return obj
            
        pretty_json = json.dumps(
            validation_results, 
            indent=2, 
            ensure_ascii=False,
            default=decimal_serializer
        )
        
        # Log validation summary
        overall_status = validation_results.get("overall_status", "UNKNOWN")
        logger.info(f"✅ Validation complete. Overall status: {overall_status}")
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        import traceback
        logger.error(f"❌ Error in validation endpoint: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        error_response = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "error": "Internal server error",
            "validation_summary": {
                "overall_status": "ERROR"
            },
            "message": "Validation endpoint encountered an error"
        }
        error_json = json.dumps(error_response, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

@app.post("/cache_clear")
async def clear_cache_endpoint(request: Request):
    """
    Manually clear the cache (force refresh on next request).
    Requires ADMIN_TOKEN in Authorization header.

    Returns:
        Success/error message
    """
    admin_token = os.getenv('ADMIN_TOKEN', '')
    if not admin_token:
        return Response(
            content=json.dumps({"error": "Cache clear is disabled (no ADMIN_TOKEN configured)"}, indent=2),
            media_type="application/json",
            status_code=403
        )
    auth = request.headers.get('Authorization', '')
    if auth != f"Bearer {admin_token}":
        return Response(
            content=json.dumps({"error": "Unauthorized"}, indent=2),
            media_type="application/json",
            status_code=401
        )
    try:
        from ticker_formatting_cached import clear_cache

        result = clear_cache()
        
        pretty_json = json.dumps(result, indent=2, ensure_ascii=False)
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"❌ Error in cache_clear endpoint: {e}")
        error_json = json.dumps({"error": "Internal server error"}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )


@app.get("/stats", response_class=HTMLResponse)
async def get_stats():
    """
    Stats endpoint with ERC20 formatting applied (like /coingecko endpoint)
    Returns HTML page with ERC20 symbols for exported currencies
    """
    try:
        from fastapi.responses import HTMLResponse
        from cache_manager import get_cached_pairs_data_only
        from currency_price_cache import get_currency_usd_price, load_currency_config
        from currency_price_cache import get_vrsc_usd_price
        from liquidity_calculator import get_chain_usd_price
        from dict import get_symbol_for_currency
        
        logger.info("🔄 Generating CoinGecko stats HTML with ERC20 formatting...")
        
        # Get cached pairs data (raw internal format)
        raw_data = get_cached_pairs_data_only()
        
        if 'error' in raw_data:
            logger.error(f"Error getting cached data: {raw_data['error']}")
            return HTMLResponse("<html><body><h1>Error: No cached data available</h1></body></html>")
        
        pairs_data = raw_data.get('pairs', [])
        
        # Filter out converter currency pairs
        from dict import is_converter_currency
        filtered_pairs = []
        for pair in pairs_data:
            base_currency_id = pair.get('base_currency_id', '')
            target_currency_id = pair.get('target_currency_id', '')
            
            if not (is_converter_currency(base_currency_id) or is_converter_currency(target_currency_id)):
                filtered_pairs.append(pair)
        
        # Calculate USD volumes using INTERNAL Verus currency names
        def get_base_currency_usd_rate(currency: str) -> float:
            """Get USD rate for internal Verus currency names"""
            try:
                # Tier 1: Stablecoins - fixed at $1.00 (load from currency_config.json)
                try:
                    import json
                    with open('currency_config.json', 'r') as f:
                        config = json.load(f)
                    stablecoins = config.get('stablecoins', [])
                except:
                    # Fallback to hardcoded list if config file not available
                    stablecoins = [
                        'DAI.vETH', 'USDC.vETH', 'USDT.vETH', 'TUSD.vETH', 'BUSD.vETH', 'FRAX.vETH', 'scrvUSD.vETH'
                    ]
                
                if currency in stablecoins:
                    return 1.0
                
                # Tier 2: Chain native currencies
                if currency == 'VRSC':
                    return get_vrsc_usd_price()
                elif currency in ['CHIPS', 'vARRR', 'vDEX']:
                    chain_map = {'vARRR': 'VARRR', 'vDEX': 'VDEX'}
                    chain = chain_map.get(currency, currency)
                    return get_chain_usd_price(chain)
                
                # Tier 3: Specific conversions - use currency_price_cache system
                cached_price = get_currency_usd_price(currency)
                if cached_price > 0:
                    return cached_price
                
                return 0.0
                
            except Exception as e:
                logger.error(f"Error getting USD rate for {currency}: {e}")
                return 0.0
        
        # Process pairs with USD calculations and ERC20 formatting
        processed_pairs = []
        base_currency_rates = {}  # Cache rates
        
        for pair in filtered_pairs:
            base_currency = pair.get('base_currency', '')
            target_currency = pair.get('target_currency', '')
            base_currency_id = pair.get('base_currency_id', '')
            target_currency_id = pair.get('target_currency_id', '')
            base_volume = float(pair.get('base_volume', 0))
            
            # Calculate USD rate using INTERNAL currency name
            cache_key = f"usd_rate_{base_currency}"
            if cache_key not in base_currency_rates:
                base_currency_rates[cache_key] = get_base_currency_usd_rate(base_currency)
            base_usd_rate = base_currency_rates[cache_key]
            
            # Calculate USD volume
            usd_volume = base_volume * base_usd_rate
            
            # Get liquidity in USD (stored as 'pair_liquidity_usd' in raw data)
            liquidity_usd = float(pair.get('pair_liquidity_usd', 0))
            
            # Apply ERC20 formatting for display names
            base_symbol = get_symbol_for_currency(base_currency_id) or base_currency
            target_symbol = get_symbol_for_currency(target_currency_id) or target_currency
            
            # Create ticker with ERC20 formatted names
            ticker = {
                'ticker_id': f"{base_symbol}-{target_symbol}",
                'base_currency': base_symbol,
                'target_currency': target_symbol,
                'pool_id': pair.get('converter', ''),
                'last_price': float(pair.get('last', 0)),
                'base_volume': base_volume,
                'target_volume': float(pair.get('target_volume', 0)),
                'high': float(pair.get('high', 0)),
                'low': float(pair.get('low', 0)),
                'open': float(pair.get('open', 0)),
                'volume_usd': usd_volume,
                'liquidity_in_usd': liquidity_usd
            }
            
            processed_pairs.append(ticker)
        
        # Sort by USD volume (descending)
        processed_pairs.sort(key=lambda x: float(x.get('volume_usd', 0)), reverse=True)
        
        # Calculate total stats
        total_pairs = len(processed_pairs)
        total_volume_usd = sum(float(ticker.get('volume_usd', 0)) for ticker in processed_pairs)
        
        # Generate table rows
        table_rows = ""
        for pair in processed_pairs:
            table_rows += f"""
                <tr>
                    <td class="pair-name">{pair['ticker_id']}</td>
                    <td class="price">{pair['last_price']:.8f}</td>
                    <td class="volume">{pair['base_volume']:.4f}</td>
                    <td class="volume">${pair['volume_usd']:.2f}</td>
                    <td class="price">{pair['high']:.8f}</td>
                    <td class="price">{pair['low']:.8f}</td>
                    <td class="pool-id">{pair['pool_id']}</td>
                </tr>
            """
        
        # Generate HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Verus DEX Market Data (ERC20 Format)</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #1a1a1a;
                    color: #ffffff;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                }}
                h1 {{
                    text-align: center;
                    color: #4CAF50;
                    margin-bottom: 30px;
                }}
                .stats {{
                    margin-bottom: 20px;
                    padding: 15px;
                    background-color: #2d2d2d;
                    border-radius: 8px;
                }}
                .refresh-btn {{
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 5px;
                    cursor: pointer;
                    margin-bottom: 20px;
                }}
                .refresh-btn:hover {{
                    background-color: #45a049;
                }}
                .price-bar {{
                    margin-bottom: 20px;
                    padding: 15px;
                    background-color: #2d2d2d;
                    border-radius: 8px;
                    display: flex;
                    flex-wrap: wrap;
                    gap: 15px;
                }}
                .price-item {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    min-width: 80px;
                }}
                .price-label {{
                    font-size: 0.8em;
                    color: #888;
                    margin-bottom: 4px;
                }}
                .price-value {{
                    font-size: 1.1em;
                    font-weight: bold;
                    color: #4CAF50;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    background-color: #2d2d2d;
                    border-radius: 8px;
                    overflow: hidden;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
                }}
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #404040;
                }}
                th {{
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                }}
                tr:hover {{
                    background-color: #3d3d3d;
                }}
                .pair-name {{
                    font-weight: bold;
                    color: #4CAF50;
                }}
                .volume {{
                    color: #FFA726;
                    font-weight: bold;
                }}
                .price {{
                    color: #42A5F5;
                }}
                .liquidity {{
                    color: #AB47BC;
                }}
                .pool-id {{
                    color: #66BB6A;
                    font-size: 0.9em;
                }}
                .auto-refresh {{
                    color: #888;
                    font-size: 0.9em;
                    margin-top: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="stats-header">
                    <h1>Verus DEX Market Data (ERC20 Format)</h1>
                    <p><strong>Total Trading Pairs:</strong> {total_pairs}</p>
                    <p><strong>Total 24h Volume:</strong> ${total_volume_usd:.2f}</p>
                </div>
                
                <div class="price-bar">
        """
        
        # Add currency prices to price bar with ERC20 formatting
        currency_prices = {}
        
        # Get specific conversion prices from cache
        try:
            from currency_price_cache import get_all_currency_prices
            specific_prices = get_all_currency_prices()
            for currency, price in specific_prices.items():
                currency_prices[currency] = price
        except:
            pass
        
        # Get chain native currency prices
        currency_prices['VRSC'] = get_base_currency_usd_rate('VRSC')
        currency_prices['CHIPS'] = get_base_currency_usd_rate('CHIPS')
        currency_prices['vARRR'] = get_base_currency_usd_rate('vARRR')
        currency_prices['vDEX'] = get_base_currency_usd_rate('vDEX')
        
        # Add currency prices to price bar with ERC20 formatting
        for currency, price in currency_prices.items():
            if price > 0:
                # Apply ERC20 formatting to currency name for display
                display_name = currency  # Default to internal name
                
                # Look for this currency in the pairs data to get its ID for ERC20 symbol
                for pair in filtered_pairs:
                    if pair.get('base_currency') == currency:
                        currency_id = pair.get('base_currency_id', '')
                        display_name = get_symbol_for_currency(currency_id) or currency
                        break
                    elif pair.get('target_currency') == currency:
                        currency_id = pair.get('target_currency_id', '')
                        display_name = get_symbol_for_currency(currency_id) or currency
                        break
                
                html_content += f"""
                    <div class="price-item">
                        <div class="price-label">{display_name}</div>
                        <div class="price-value">${price:.4f}</div>
                    </div>
                """
        
        html_content += f"""
                </div>
                
                <table>
                    <thead>
                        <tr>
                            <th>Trading Pair</th>
                            <th>Last Price</th>
                            <th>Base Volume</th>
                            <th>24h Volume (USD)</th>
                            <th>24h High</th>
                            <th>24h Low</th>
                            <th>Pool ID</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows}
                    </tbody>
                </table>
                
            </div>
        </body>
        </html>
        """
        
        logger.info(f"✅ Generated CoinGecko stats HTML with ERC20 formatting: {total_pairs} pairs, total USD volume: ${total_volume_usd:.2f}")
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error(f"Error generating stats page: {e}")
        return HTMLResponse(content="<h1>Internal server error</h1>", status_code=500)


if __name__ == "__main__":

    # Kill any existing processes on the port
    kill_process_on_port(8765)

    print("Starting Verus Ticker API v4 on port 8765")

    # Initialize cache manager and start background refresh
    print("Initializing cache manager...")
    from cache_manager import get_cache_manager
    cache_manager = get_cache_manager(cache_ttl_seconds=60)
    print("Cache manager initialized with background refresh enabled")

    print("Launching FastAPI server on http://localhost:8765")

    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8765)
