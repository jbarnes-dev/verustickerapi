#!/usr/bin/env python3
"""
Verus Ticker API - FastAPI Implementation
Core FastAPI skeleton with basic structure and health checks
"""

from datetime import datetime
import json
import logging
import os
import signal
import subprocess
import sys
import traceback
import time
from typing import Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse
from fastapi.responses import JSONResponse as BaseJSONResponse

from cache_manager import get_cache_status, get_cached_pairs_data_only, get_cache_manager
from data_integration import extract_all_pairs_data
from block_height import start_new_session, clear_session
from converter_discovery import discover_active_converters
from ticker_formatting import format_iaddress_coinmarketcap_tickers
from ticker_formatting import generate_coingecko_tickers
from ticker_formatting import generate_coinmarketcap_enhanced_tickers
from ticker_formatting import generate_coinpaprika_tickers
from verussupply import get_vrsc_supply
from verus_rpc import make_rpc_call

# Load environment variables
load_dotenv()

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
    title="Verus Ticker API",
    description="Real-time cryptocurrency ticker data from Verus blockchain",
    version="1.0.0",
    docs_url=None,
    redoc_url=None
)

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
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception on {request.url}: {str(exc)}")
    return PrettyJSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

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
    """Clean and Simple VRSC/vETH Trace Process Documentation"""
    base_url = os.environ['BASE_URL']
    # TODO: Change to use templates. Something's funky with the HTML preventing this. 
    with open('templates/index.html', 'r') as f:
        f = f.readlines()
    html_content = ''.join(f).replace('{{ base_url }}', base_url)
    return HTMLResponse(content=html_content)

# Multi-chain converter discovery endpoint
@app.get("/converters")
async def get_converters(chain: str = None):
    """
    Get converter discovery data with optional chain filtering
    
    Args:
        chain: Optional chain filter (VRSC, CHIPS, VARRR, VDEX). If not specified, returns all chains.
    """
    try:
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
            result = discover_active_converters(chains=chains)
            
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
            content={"error": f"Internal server error: {str(e)}"},
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
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = generate_coingecko_tickers(pairs_list, use_cache=False)
            return PrettyJSONResponse(content=tickers_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": f"Internal server error: {str(e)}"}, status_code=500)
    
    @app.get("/coinmarketcap_live") 
    async def get_coinmarketcap_live():
        """Live CoinMarketCap endpoint - makes fresh RPC calls"""
        try:
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = generate_coinmarketcap_enhanced_tickers(pairs_list)
            return PrettyJSONResponse(content=tickers_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": f"Internal server error: {str(e)}"}, status_code=500)
    
    @app.get("/coinpaprika_live")
    async def get_coinpaprika_live():
        """Live Coinpaprika endpoint - makes fresh RPC calls"""
        try:
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
            return PrettyJSONResponse(content={"error": f"Internal server error: {str(e)}"}, status_code=500)
    
    @app.get("/coinmarketcap_iaddress_live")
    async def get_coinmarketcap_iaddress_live():
        """Live CMC I-Address endpoint - makes fresh RPC calls"""
        try:
            
            pairs_data = extract_all_pairs_data()
            if 'error' in pairs_data:
                return PrettyJSONResponse(content={"error": "Failed to extract trading pairs data"}, status_code=503)
            
            pairs_list = pairs_data.get('pairs', [])
            if not pairs_list:
                return PrettyJSONResponse(content={"error": "No trading pairs available"}, status_code=503)
            
            tickers_data = format_iaddress_coinmarketcap_tickers(pairs_list)
            return PrettyJSONResponse(content=tickers_data)
        except Exception as e:
            return PrettyJSONResponse(content={"error": f"Internal server error: {str(e)}"}, status_code=500)
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



# Removed unused /enhanced endpoint

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
        error_json = json.dumps({"error": str(e)}, indent=2)
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
        error_json = json.dumps({"error": str(e)}, indent=2)
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
        error_json = json.dumps({"error": str(e)}, indent=2)
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
        logger.error(f"❌ Error in validation endpoint: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        error_response = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "error": str(e),
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
async def clear_cache_endpoint():
    """
    Manually clear the cache (force refresh on next request)
    
    Returns:
        Success/error message
    """
    try:
        result = clear_cache()
        
        pretty_json = json.dumps(result, indent=2, ensure_ascii=False)
        
        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"❌ Error in cache_clear endpoint: {e}")
        error_json = json.dumps({"error": str(e)}, indent=2)
        return Response(
            content=error_json,
            media_type="application/json",
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

if __name__ == "__main__":
    import uvicorn
    
    # Kill any existing processes on the port
    kill_process_on_port(8765)
    
    print("Starting Verus Ticker API on port 8765")
    
    # Initialize cache manager and start background refresh
    print("Initializing cache manager...")
    cache_manager = get_cache_manager(cache_ttl_seconds=60)
    print("Cache manager initialized with background refresh enabled")
    
    print("Launching FastAPI server on http://localhost:8765")
    
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8765)
