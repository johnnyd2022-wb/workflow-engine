#!/bin/bash

# test-container-registry-token
test_container_registry_token = "glpat-hj-o1IbGGqsxJQ91vfw8iG86MQp1OmcxNnA2Cw.01.121kpm83q"

wb_test_build() {
        cd /home/johnny/wb_local
        cp -r * /home/johnny/wb_conn_test/
        cd /home/johnny
        find /home/johnny/wb_conn_test -type f -exec sed -i 's/localhost/host.docker.internal/g' {} +
        find /home/johnny/wb_conn_test -type f -exec sed -i 's/5005/5001/g' {} +
        sed -i '/schedule/d' '/home/johnny/wb_conn_test/app.py'
        sed -i 's/client_id="40ADFC7B008F4AD1B75EE9D741DFE1F8",/client_id="78E456E3612149A8A8C4D1A99D4BEE01",/g' '/home/johnny/wb_conn_test/app.py'
        sed -i 's/client_secret="SiKz3A-2ramUbm5oqNP_fTnE-cPu7rwIruLN4CYQqgrUmomI",/client_secret="Kz2uZRvEGWq-XSFVU
_hEMj9ceb5U942YPoJ3qu_NpGdxcAu7",/g' '/home/johnny/wb_conn_test/app.py' docker stop $(docker ps -aqf "name=wb_inv_test") docker rm $(docker ps -aqf "name=wb_inv_test")
        docker build -f Dockerfile-test -t wb_inv:test .
        source /home/johnny/.bashrc
        wb_test_run
        docker-update
}

wb_test_build()