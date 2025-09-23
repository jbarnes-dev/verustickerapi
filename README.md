# 🔍 Verus Ticker API

**Version:** 3.0 | **Status:** ✅ Active | **Base URL:** http://localhost:8765

A high-performance API for Verus blockchain trading pair data with multi-format endpoint support and intelligent caching.

## 🚀 Features

- **Multi-format Support**: CoinGecko, CoinMarketCap, and Coinpaprika compatible endpoints
- **Intelligent Caching**: 60-second TTL for production endpoints with background refresh
- **Live Debug Endpoints**: Real-time RPC data for development and testing
- **Volume-weighted Pricing**: Accurate price aggregation across multiple converters
- **ERC20 Symbol Mapping**: Automatic symbol conversion for cross-chain compatibility
- **Health Monitoring**: Built-in status and cache monitoring endpoints

## 📋 API Endpoints

### 🏥 Health & Status

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status, RPC connection, and cache information |
| `/verussupply` | GET | Verus supply information |
| `/stats` | GET | Coingecko format with USD Volume as HTML |

### ⚡ Cached Endpoints (60s TTL)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/coingecko` | GET | CoinGecko format ticker data (cached) |
| `/coinmarketcap` | GET | CoinMarketCap format ticker data (cached) |
| `/coinpaprika` | GET | Coinpaprika format ticker data (cached) |
| `/coinmarketcap_iaddress` | GET | CMC I-Address format with Verus native IDs (cached) |

### 📊 Live Debug Endpoints (Disabled by default)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/coingecko_live` | GET | CoinGecko format with fresh RPC calls |
| `/coinmarketcap_live` | GET | CoinMarketCap format with fresh RPC calls |
| `/coinpaprika_live` | GET | Coinpaprika format with fresh RPC calls |
| `/coinmarketcap_iaddress_live` | GET | CMC I-Address format with fresh RPC calls |

## 🔧 Setup & Installation

### Prerequisites

- Python 3.8+
- Verus daemon running with RPC access
- Required Python packages: `fastapi`, `uvicorn`, `requests`

### Environment Configuration

Create a `.env` file with your RPC credentials:

```env
# VRSC (Verus) RPC Connection
VERUS_RPC_HOST=127.0.0.1
VERUS_RPC_PORT=27486
VERUS_RPC_USER=your_rpc_user
VERUS_RPC_PASSWORD=your_rpc_password

# Enable live endpoints (optional, for debugging)
ENABLE_LIVE_ENDPOINTS=false
```

### Running the API

```bash
python3 main.py
```

The API will be available at `http://localhost:8765`

## 📊 Response Formats

### CoinGecko Format
```json
[
  {
    "ticker_id": "VRSC_DAI.vETH",
    "pool_id": "iH37kRsdfoHtHK5TottP1Yfq8hBSHz9btw",
    "base_currency": "VRSC",
    "target_currency": "DAI.vETH",
    "last_price": "2.15310337",
    "base_volume": "1234.56789",
    "target_volume": "2658.91234"
  }
]
```

### CoinMarketCap Format
```json
{
  "0": {
    "base_id": "0x67F4C72a50f8Df6487720261E188F2abE83F57D7",
    "base_name": "VRSC",
    "base_symbol": "VRSC",
    "quote_id": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "quote_name": "DAI.vETH",
    "quote_symbol": "DAI.vETH",
    "last_price": "2.15310337",
    "base_volume": "1234.56789",
    "quote_volume": "2658.91234"
  }
}
```

### Coinpaprika Format (VerusStatisticsAPI Compatible)
```json
{
  "code": "200000",
  "data": {
    "time": 1756195613998,
    "ticker": [
      {
        "symbol": "VRSC-DAI.vETH",
        "symbolName": "VRSC-DAI.vETH",
        "volume": "1234.56789000",
        "last": "2.15310337",
        "high": "2.20000000",
        "low": "2.10000000",
        "open": "2.18000000"
      }
    ]
  }
}
```

## 🔍 Key Features

### Intelligent Caching System
- **60-second cache TTL** for production endpoints
- **Background refresh** prevents cache misses
- **Proactive updates** on new block detection
- **Memory-efficient** storage with automatic cleanup

### Volume-Weighted Price Aggregation
When multiple converters trade the same pair, prices are aggregated using quote volume weighting:

```
weighted_price = (price1 × quote_vol1 + price2 × quote_vol2) / (quote_vol1 + quote_vol2)
```

### Multi-Chain Support
- **VRSC** (Verus) - Primary chain
- **CHIPS** - Gaming and DeFi
- **VARRR** - Privacy-focused
- **VDEX** - Decentralized exchange

## 🛠️ Development

### Live Endpoints
Enable live endpoints for development by setting `ENABLE_LIVE_ENDPOINTS=true` in your `.env` file. Live endpoints make fresh RPC calls and are slower but provide real-time data.

### Health Monitoring
Use `/health` endpoint to monitor:
- RPC connection status
- Cache status and refresh times
- Current block heights
- System performance metrics

## 📈 Performance

- **Cached endpoints**: ~50ms response time
- **Live endpoints**: ~2-5s response time (RPC dependent)
- **Cache hit ratio**: >95% under normal load
- **Concurrent requests**: Supports 100+ simultaneous connections

## 🔒 Security

- RPC credentials stored in environment variables
- No sensitive data exposed in API responses
- Rate limiting on live endpoints
- Input validation and sanitization

## 📝 License

This project is licensed under the MIT License.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📞 Support

For issues and questions:
- Create an issue on GitHub
- Check the `/health` endpoint for system status
- Review logs for debugging information

---

**Built with ❤️ for the Verus ecosystem**
