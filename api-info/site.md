Welcome to the FortiAnalyzer JSON API!

This document provides both query and response of FortiAnalyzer JSON API.  The JSON API is based on JSON-RPC, a remote procedure call protocol encoded in JSON.

To communicate with a FortiAnalyzer via the API, a client program must send HTTP POST request to https://<faz_ip>/jsonrpc, where <faz_ip> is the IP address or FQDN of the FortiAnalyzer.

Message Format
The format of JSON request:

 

{
    "id": 1,
    "method": "...",
    "params": [ ... ],
    "session": "..."
}
 

Properties	Descriptions
method	Supports get, add, set, update, delete, move, clone, replace, and execute. Refer to the reference for individual module for more information about availability, parameters, and response format.
params	Refer to the reference for individual module for the list of parameters available for each method.
session	The cookie of an active session on FortiAnalyzer. FortiAnalyzer requires a valid session in order to perform an operation via API. Refer to sys/login/user and sys/logout for creating a session using JSON API.
id	An integer value which will be matched in the response data.
The format of JSON response:

{
    "id": 1,
    "result": [
        "data": [ ... ],
        "status": {
            "code": 0,
            "message": "OK"
        },
        "url": "..."
    ],
    "session": "..."
}
data: may not exist if there is no any object attribute is returned
code:  code of the API request execution, 0 means success
message: text message for the API request execution