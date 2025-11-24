curl --http1.1 -X POST https://identity.xero.com/connect/token \
  -H "Authorization: Basic $(echo -n '40ADFC7B008F4AD1B75EE9D741DFE1F8:6_sRqbm6tUam3z9T0Av8GBgo4d1_1fz4anTgjd0qu0yvImaq' | base64)" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "redirect_uri=http://127.0.0.1:5005/xeroauth"
