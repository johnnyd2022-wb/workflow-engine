#!/bin/bash

# prod-container-registry-token
prod_container_registry_token = "glpat-PY91V7OXIYcBU5cf8I3yrm86MQp1OmcxNnA2Cw.01.1203li228"

# Local execution
wb_app_build_local() {
        source ~/.bashrc
        /home/johnny/app_backups.sh
        /home/johnny/db_backups.sh
        cd /home/johnny/wb_local
        cp -r * /home/johnny/wb_conn/
        cd /home/johnny
        find /home/johnny/wb_conn -type f -exec sed -i 's/localhost/host.docker.internal/g' {} +
        find /home/johnny/wb_conn -type f -exec sed -i 's/5005/5000/g' {} +
}

wb_app_build() {
        /home/johnny/app_backups.sh
        /home/johnny/db_backups.sh
        cd /home/johnny/wb_local
        cp -r * /home/johnny/wb_conn/
        cd /home/johnny
        find /home/johnny/wb_conn -type f -exec sed -i 's/localhost/host.docker.internal/g' {} +
        find /home/johnny/wb_conn -type f -exec sed -i 's/5005/5000/g' {} +
        find /home/johnny/wb_conn -type f -exec sed -i 's/5401: 5432/5432: 5432/g' {} +
        find /home/johnny/wb_conn -type f -exec sed -i 's/port = 5401/port = 5432/g' {} +
        find /home/johnny/wb_conn -type f -exec sed -i 's/5401/5432/g' {} +
        find /home/johnny/wb_conn -type f -exec sed -i 's/whistlebird_db_test/whistlebird_db_prod/g' {} +
        sed -i 's/client_id="40ADFC7B008F4AD1B75EE9D741DFE1F8",/client_id="5DD1424E67EE4F9F97E19C04418E354C",/g' '/home/johnny/wb_conn/app.py'
        sed -i 's/client_secret="SiKz3A-2ramUbm5oqNP_fTnE-cPu7rwIruLN4CYQqgrUmomI",/client_secret="zAUkEVc_p28me3hNtN-K_1QatMJCnVLrL6ggdZJZPAB88VZ9",/g' '/home/johnny/wb_conn/app.py'
        sed -i "s/receiver_email = 'johnny@whistlebird.co.nz'/receiver_email = 'whistlebird@whistlebird.co.nz'/g" '/home/johnny/wb_conn/app.py'
        docker stop $(docker ps -aqf "name=wb_inv_prod")
        docker rm $(docker ps -aqf "name=wb_inv_prod")
        docker build -f Dockerfile -t wb_inv:prod .
        source /home/johnny/.bashrc
        wb_app_run
        docker-update
}

wb_app_build()