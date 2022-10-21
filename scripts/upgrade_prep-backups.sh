#!/usr/bin/env bash

# Upgrade Prep - backups
# A script designed to work by pasting directly into a terminal in addition to running as a script
# Run this to take additional backups for due diligence beyond LogicHub's built-in backup script


process_input() {
    no_logs="false"
    no_lh_backup="false"
    delete_dir="false"
    while true; do
        if [[ -z "$1" ]]; then
            break
        elif [[ "$1" == "--no-logs" ]]; then
            no_logs="true"
        elif [[ "$1" == "--no-lh-backup" ]]; then
            no_lh_backup="true"
        elif [[ "$1" == "--delete-dir" ]]; then
            delete_dir="true"
        else
            print_color -red "ERROR: New param called $1; aborting...\n"
            return
        fi
        shift
    done
}

print_color() {
    newline='\n'
    header=''
    tail=''
    color=4  # Default: Set color to blue
    while true; do
        # Next, set to specific color/style if requested, otherwise set to default color
        if [[ $1 == '-nocolor' || $1 == '--nocolor' ]]; then
            color=''
        elif [[ $1 == '-nocolorbold' || $1 == '--nocolorbold' ]]; then
            color=''
            tput bold
        elif [[ $1 == '-n' ]]; then
            # No trailing line break
            newline=''
        elif [[ $1 == '-h' || $1 == '--header' ]]; then
            header='\n***** '
            tail='\n'
        elif [[ $1 == '-red' || $1 == '--red' ]]; then
            color=1
        elif [[ $1 == '-blue' || $1 == '--blue' ]]; then
            color=4
        elif [[ $1 == '-gray' || $1 == '--gray' ]]; then
            color=8
        elif [[ $1 == '-invert' || $1 == '--invert' ]]; then
            tput rev  # invert colors
        else
            break
        fi
        shift
    done

    # Set text color
    if [[ ${color} != '' ]]; then
        # First, make text bold
        tput bold
        tput setaf ${color}
    fi

    # print the provided text in the requested style/color
    printf "${header}${*}${tail}${newline}"

    # Reset text
    tput sgr0
}

make_vars() {
    current_user=$(whoami)
    starting_dir=$(pwd)
    new_dir="upgrade_backups_$(date +%Y%m%d_%H%M%S)"
    new_dir_full="${starting_dir}/${new_dir}"
    service_backup_dir_name="logichub_service_backup_$(date +%Y%m%d_%H%M%S)"
    service_backup_dir_full="/opt/docker/${service_backup_dir_name}"
}

function trim {
    local var="$*"
    # remove leading whitespace characters
    var="${var#"${var%%[![:space:]]*}"}"
    # remove trailing whitespace characters
    var="${var%"${var##*[![:space:]]}"}"
    echo -n "$var"
}

run_backups() {
    process_input "$@"

    make_vars

    [[ ${current_user} != "centos" && ${current_user} != "logichub" && ${current_user} != "ubuntu" ]] && { print_color -red "Current user (${current_user}) is not centos, ubuntu, or logichub.\nsu to one of those users and try again.\n"; return; }

    print_color -h "Host Files"
    print_color --nocolorbold "Creating new backup directory: ${new_dir_full}"
    mkdir "${new_dir_full}" || { print_color -red "ERROR: New directory creation failed; aborting...\n"; return; }

    new_file_InstallerSettings="InstallerSettings.conf"
    print_color --nocolorbold "Backing up: ${new_file_InstallerSettings}"
    sudo cp -p /opt/logichub/InstallerSettings.conf "${new_dir}/"
    ls -l "${new_dir}/${new_file_InstallerSettings}"

    print_color --nocolorbold "\nChecking for requests_ca_bundle certs..."
    # Show the files that will be backed up
    sudo find /opt/logichub/certs/ \( -name "*.crt" -o -name "*.pem" \)
    # Now actually back them up
    mkdir "${new_dir}/certs"
    sudo find /opt/logichub/certs/ \( -name "*.crt" -o -name "*.pem" \) -exec cp -p "{}" "${new_dir}/certs" \;

    print_color -h "Log Backup"
    if [[ "${no_logs}" == "true" ]]; then
        print_color -gray "Skip requested..."
    else
        new_file_logs="${new_dir_full}_logs.tar.gz"
        print_color --nocolorbold "Backing up LogicHub logs (except thread dumps): ${new_file_logs}"
        log_temp_dir="${new_dir}/logs"
        mkdir "${log_temp_dir}"
        print_color --nocolorbold "gzipping all raw, archived postgresql files..."
        sudo find /var/log/logichub/postgres -type f -name "*.log" -not -wholename "$(ls -tr /var/log/logichub/postgres/postgresql-2* |tail -n1)" -exec gzip "{}" \;
        # Begin copying files
        print_color --nocolorbold "Copying logs before tarring..."
        sudo find /var/log/logichub/* -maxdepth 0 -type d -not -name threaddumps -exec cp -rp "{}" "${log_temp_dir}" \;
        sudo chown -R ${current_user}:${current_user} "${log_temp_dir}"
        print_color --nocolorbold "Tarring..."
        tar czf ${new_file_logs} "${log_temp_dir}"
        rm -rf "${log_temp_dir}"
    fi

    print_color -h "LogicHub Backup Script"
    if [[ "${no_lh_backup}" == "true" ]]; then
        print_color -gray "Skip requested..."
    else
        print_color --nocolorbold "Generating a backup..."
        sudo /opt/logichub/scripts/backup.sh
        new_backup="$(sudo ls -tr /opt/logichub/backups/|tail -n1)"
        print_color --nocolorbold -n "\nNew backup: $(print_color "/opt/logichub/backups/${new_backup}")"
    fi

    print_color -h "Service Container Backups"

    # ToDo Add backup of ML models: /opt/docker/data/shared/

    # create a folder for backups inside the service container
    print_color --nocolorbold "Creating backup folder within the service container: ${service_backup_dir_full}"
    docker exec -it service mkdir ${service_backup_dir_full}

    new_file_data_service="${service_backup_dir_full}/logichub_backup_data_service.tar.gz"
    print_color --nocolorbold "Backing up /opt/docker/data/service : ${new_file_data_service}"
    docker exec -it service tar czf ${new_file_data_service} -C /opt/docker/data/ service/

    new_file_root_home="${service_backup_dir_full}/logichub_backup_root.tar.gz"
    print_color --nocolorbold "Backing up /root : ${new_file_root_home}"
    docker exec -it service tar czf ${new_file_root_home} -C / root/

    new_file_conf="${service_backup_dir_full}/logichub_backup_opt_docker_conf.tar.gz"
    print_color --nocolorbold "Backing up /opt/docker/conf: ${new_file_conf}"
    docker exec -it service tar czf ${new_file_conf} -C /opt/docker/ conf/

    new_file_resources="${service_backup_dir_full}/logichub_backup_opt_docker_resources.tar.gz"
    print_color --nocolorbold "Backing up /opt/docker/resources: ${new_file_resources}"
    docker exec -it service tar czf ${new_file_resources} -C /opt/docker/ resources/

    user_steps_dir=$(docker exec -it service cat /opt/docker/data/service/conf/dynamic.conf | grep "lhub.steps.userdefined.dir"|grep -Po '=\s*\K.*')
    if [[ -z "${user_steps_dir}" ]]; then
        print_color -gray "lhub.steps.userdefined.dir not defined in dynamic.conf; skipping..."
    else
        user_steps_dir=$(trim "${user_steps_dir}")
        new_file_custom_modules="${service_backup_dir_full}/logichub_backup_opt_docker_custom_modules.tar.gz"
        print_color --nocolorbold "Backing up legacy user-defined modules (lhub.steps.userdefined.dir): ${new_file_custom_modules}"
        docker exec -it service tar czf ${new_file_custom_modules} -C /opt/docker/data/service/ user-steps/
    fi

    print_color --nocolorbold "Tarring backups files inside service container: ${service_backup_dir_full}"
    service_backup_file="${service_backup_dir_full}.tar.gz"
    docker exec -it service tar czf "${service_backup_file}" -C "/opt/docker/" "${service_backup_dir_name}"

    print_color --nocolorbold "Copying from service container to host"
    docker cp service:${service_backup_file} "${new_dir_full}"
    docker exec -it service rm -rf "${service_backup_dir_full}" "${service_backup_file}"

    new_file_python_modules="logichub_backup_installed_python_modules.txt"
    print_color --nocolorbold "\nGenerating: ${new_file_python_modules}"
    docker exec -it service pip list > "${new_dir}/${new_file_python_modules}"
    ls -l "${new_dir}/${new_file_python_modules}"

    new_file_service_bash_history="logichub_backup_service_root_bash_history.txt"
    print_color --nocolorbold "\nGenerating: ${new_file_service_bash_history}"
    docker exec -it service cat /root/.bash_history > "${new_dir}/${new_file_service_bash_history}"
    ls -l "${new_dir}/${new_file_service_bash_history}"

    print_color --nocolorbold "\nBacking up custom descriptors"
    oldest_file_date=$(docker exec -it service ls -ltr /opt/docker/resources/integrations | grep -P "\.json(?=[\r\n]|$)" | head -n1 | grep -Po '(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +\d+ +\d{2}:?\d{2}')
    readarray -t custom_descriptors < <(docker exec -it service ls -l /opt/docker/resources/integrations | grep -v "${oldest_file_date}" | grep -Po "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +\d+ +\d{2}:?\d{2} +\K\w.*json")
    descriptor_dir="${new_dir}/descriptors"
    mkdir "${descriptor_dir}"
    for i in "${custom_descriptors[@]}"; do
        x="$(trim "${i}")"
        docker cp "service:/opt/docker/resources/integrations/${x}" "${descriptor_dir}" || { print_color -red "ERROR: Failure during file copy; aborting...\n"; return; }
    done

# 2021-08-02: no longer relevant, since the LogicHub backup script is more thorough now, and this workaround only backs up one of the necessary databases anyway.
#    print_color -h "Postgres Database"
#
#    new_file_db_dump="logichub_backup_data_dump.psql"
#    print_color --nocolorbold "Generating: ${new_file_db_dump}"
#    docker exec -it postgres pg_dump --username daemon -d lh > "${new_dir}/${new_file_db_dump}"
#    ls -l "${new_dir}/${new_file_db_dump}"

    new_file_lh_users="db-users.txt"
    print_color --nocolorbold  "\nGenerating: ${new_file_lh_users}"
    docker exec -it postgres psql -P pager --u daemon lh -c "select * from users;" > "${new_dir}/${new_file_lh_users}"
    ls -l "${new_dir}/${new_file_lh_users}"

    print_color -h "Integrations"

    new_file_integration_instances="db-integration_instances.txt"
    print_color --nocolorbold "Generating: ${new_file_integration_instances}"
    docker exec -it postgres psql -P pager --u daemon lh -c "select * from integration_instances;" > "${new_dir}/${new_file_integration_instances}"
    ls -l "${new_dir}/${new_file_integration_instances}"

    new_file_integration_descriptors="db-integration_descriptors.txt"
    print_color --nocolorbold "\nGenerating: ${new_file_integration_descriptors}"
    docker exec -it postgres psql -P pager --u daemon lh -c "select * from integration_descriptors;" > "${new_dir}/${new_file_integration_descriptors}"
    ls -l "${new_dir}/${new_file_integration_descriptors}"

    print_color -h "Final Stage"

    sudo chown ${current_user}:${current_user} ${new_dir_full}
    print_color --nocolorbold "Tarring up all files: ${new_dir_full}.tar.gz"
    sudo tar czf "${new_dir_full}.tar.gz" "${new_dir}"
    sudo chown ${current_user}:${current_user} "${new_dir_full}.tar.gz"
    print_color --nocolorbold "\nFinal backup file: ${new_dir_full}.tar.gz"

    if [[ "${delete_dir}" == "true" ]]; then
        print_color --nocolorbold "Deleting temp directory:"
        print_color --nocolorbold "\t${new_dir_full}"
        rm -rf "${new_dir_full}" || { print_color -red "ERROR: New directory creation failed; aborting...\n\n"; return; }
    fi

}

run_backups "$@"
