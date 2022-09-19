# RGB Faucet

## Endpoints

- `/reserve/balance` returns the current faucet balance
- `/reserve/top_up` returns the first unused address of the faucet's wallet
- `/receive/<address>` sends the configured amount to `<address>`

## Authentication

Requests to the `/receive/<address>` endpoint are authenticated with an API
key to be sent in the `X-Api-Key` header.

The server-side secret is configured via the `config.py` file in the instance
directory, setting the `API_KEY` variable to the chosen string.

## Development

To install the dependencies excluding the production group:
```shell
poetry install --without production
```

To run the app in development mode:
```shell
flask --app faucet_rgb --debug run --no-reload
```

To test the development server:
```shell
curl -i localhost:5000/reserve/balance
```

To test an authenticated call to the development server:
```shell
curl -i -H 'x-api-key: defaultapikey' localhost:5000/receive/badaddress
```
will return an "unauthorized" error if the API key is wrong or an Invalid
address" error if it is correct.

## Production

To install the dependencies excluding the dev group:
```shell
poetry install --sync --without dev
```

To run the app in production mode:
```shell
waitress-serve --call 'faucet_rgb:create_app'
```

To test the production server locally:
```shell
curl -i localhost:8080/reserve/balance
```
