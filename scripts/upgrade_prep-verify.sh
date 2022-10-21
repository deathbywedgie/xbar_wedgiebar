#!/usr/bin/env bash

# Upgrade Prep - Verifications
# A script designed to work by pasting directly into a terminal in addition to running as a script
# Run this to review various details about an instance prior to an upgrade

skip_review() {
    printf "\n*********************************************************\n\n"
}

pause_for_review() {
    printf "\n\n\n\nReview: %s\n\n" "$1"
    printf "Press enter when finished reviewing..."
    read
    skip_review
}

check_recent_user_activity() {
    # New consolidated list of all users who have logged in during the current and previous log files
    previous_service_log="$(find /var/log/logichub/service -name "service.log.2*gz"| sort | tail -n1)"
    users_all=($(sudo zgrep -ohP "Login request: *\K\S+" "${previous_service_log}" /var/log/logichub/service/service.log | grep -Pv 'lh-monitoring' | sort -u))
    printf "Users who have logged in recently:\n\n"
    printf "    %s\n" "${users_all[@]}" | sort -u | grep -P ".*"

    printf "\n\nLatest activity:\n\n"
    for i in "${users_all[@]}"; do printf "    %s\n" "$(zgrep -ih "user: ${i}" "${previous_service_log}" /var/log/logichub/service/service.log | grep -P "^\d{4}-" | tail -n1 | grep "${i}")"; done | sort -u | grep -P "^ *20\d{2}-\d{2}-\d{2} [\d:.]+ [+\d]+|(?<=User: )[^\s\(]+"
    printf "\n\nCurrent date:\n\n"
    printf "    %s\n" "$(TZ=UTC date +"%Y-%m-%d %H:%M:%S (%Z)")"
    printf "\n"
}

make_sure_path_exists() {

    # ToDo Add a step to check whether Stepped Navigation is enabled in dynamic.conf

    file_path=${1}

    # If a second input was provided, use it as the user:group owner values
    owner=${2}

    # If a path was provided and it does not exist, create it and set ownership
    # If no path was provided, then skip
    [[ -n "${file_path}" ]] && [[ ! -d "${file_path}" ]] && {
        # If no owner was provided, default to "logichub:logichub"
        [[ -z "${owner}" ]] && owner="logichub:logichub"

        printf "Directory not found: %s\nCreating directory, and setting permissions to \"%s\"\n\n" "${file_path}" "${owner}"
        sudo mkdir -p "${file_path}"
        sudo chown "${owner}" "${file_path}"
    }
}

make_sure_path_exists_in_service_container() {
    file_path=${1}
    docker exec -it service mkdir -p "${file_path}"
}

run_prep_commands() {
    printf "\n\n"

    #---> CHECK: RECENT USER ACTIVITY

    check_recent_user_activity
    pause_for_review "Review recent user activity and see if instance is currently/recently in use"

    #---> CHECK: FSTAB (host)

    cat /etc/fstab
    pause_for_review "/etc/fstab: Check to be sure that there are no problems or duplicates"

    #---> CHECK: LSBLK (host)

    sudo lsblk -a
    pause_for_review "lsblk: Check to be sure that there are no problems"

    #---> CHECK: PIP-REQUIREMENTS (service container)

    matches=$(docker exec -it service find /opt/docker/data/service -name "pip-requirements.txt")
    if [[ -z "${matches}" ]]; then
        printf "pip-requirements.txt file not found. creating an empty file...\n\n"
        make_sure_path_exists_in_service_container /opt/docker/data/service/scripts
        docker exec -it service touch /opt/docker/data/service/scripts/pip-requirements.txt
        skip_review
    else
        matches="$(docker exec -it service cat /opt/docker/data/service/scripts/pip-requirements.txt)"
        if [[ -z "${matches}" ]]; then
            echo "No Python packages in pip-requirements.txt; skipping..."
            skip_review
        else
            echo "${matches}"
            pause_for_review "Review: Showing for terminal history: Python packages in pip-requirements.txt"
        fi
    fi

    #---> CHECK: PIP COMMANDS IN HISTORY (service container)

    matches=$(docker exec -it service cat /root/.bash_history | grep -P '^pip (?!list)|pip +install')
    if [[ -z "${matches}" ]]; then
        echo "No relevant pip commands in service container's bash history; skipping..."
        skip_review
    else
        echo "${matches}"
        pause_for_review "pip commands in service container's bash history... make sure no packages were installed that are not in pip-requirements.txt"
    fi

    #---> CHECK: CONF FILE REFERENCES IN HISTORY (service container)

    cmd='docker exec -it service cat /root/.bash_history | grep -v "dynamic.conf" | grep -P "\S+\.conf"'
    matches=$(eval ${cmd})
    if [[ -z "$(eval ${cmd})" ]]; then
        echo ".conf not in service container's bash history; skipping..."
        skip_review
    else
        eval ${cmd}
        pause_for_review "Take note... .conf in service container's bash history, in case unique customizations have been made that should be taken into consideration"
    fi

    #---> CHECK: Check for modified files in /opt/docker/conf (service container)

    most_common_date="$(docker exec -it service find /opt/docker/conf -type f -exec ls -l \{\} \; | grep -Po '\w+ +\d+ +[\d:]+' | uniq -c | sort -n | tail -n1 | grep -Po '[A-Za-z].*')"
    matches=$(docker exec -it service find /opt/docker/conf/ -type f -exec ls -l \{\} \; | grep -v '/opt/docker/conf/resources/steps/' | grep -v " ${most_common_date} ")
    if [[ -z "${matches}" ]]; then
        echo "No modified stock config files (/opt/docker/config) in the service container; skipping..."
        skip_review
    else
        echo "${matches}"
        pause_for_review 'One or more files modified in /opt/docker/config in the service container. These changes will NOT be carried over during an upgrade!'
    fi

    #---> CHECK: Size of /opt/docker/data/service (service container)

    make_sure_path_exists_in_service_container /opt/docker/data/service/heapdumps
    printf "/opt/docker/data/service:\n\n"
    docker exec -it service du -sh /opt/docker/data/service | grep -P "\d\S+"
    printf "\nSize of heapdumps folder:\n\n"
    docker exec -it service du -sh /opt/docker/data/service/heapdumps | grep -P "\d\S*"
    pause_for_review "size - /opt/docker/data/service (make sure this isn't excessive gzipping during backup)"

    #---> CHECK: Size of /opt/docker/resources (service container)

    docker exec -it service du -sh /opt/docker/resources | grep -P "\d\S+"
    pause_for_review "size - /opt/docker/resources (make sure this isn't excessive gzipping during backup)"

    #---> CHECK: Size of logs (host)

    make_sure_path_exists /var/log/logichub/threaddumps/
    echo "Deleting old log files"
    # Postgresql logs do not appear to be aged off like other logs, and other old files never get cleaned up, so delete all logs older than 60 days
    sudo find /var/log/logichub/postgres -type f -mtime +60 -delete
    sudo find /var/log/logichub/service -type f -mtime +60 -delete
    sudo find /var/log/logichub/threaddumps/ -type f -mtime +30 -delete

    printf "Total Log Size:\n"
    du -sh /var/log/logichub
    printf "\nThread Dumps (will be excluded):\n"
    du -sh /var/log/logichub/threaddumps/
    pause_for_review "size - /var/log/logichub (make sure this isn't excessive gzipping during backup)"

    #---> CHECK: presence of legacy custom modules (old method no longer recommended; service container)

    matches=$(docker exec -it service cat /opt/docker/data/service/conf/dynamic.conf | grep "lhub.steps.userdefined.dir"|grep -Po '=\s*\K.*')
    if [[ -z "${matches}" ]]; then
        echo "lhub.steps.userdefined.dir not defined in dynamic.conf; skipping..."
        skip_review
    else
        docker exec -it service cat /opt/docker/data/service/conf/dynamic.conf | grep -P "^\s*lhub.steps.userdefined.dir"
        pause_for_review "user-defined steps in dynamic.conf"
    fi

    #---> CHECK: presence of legacy custom integrations (old method no longer recommended; service container)

    most_common_date=$(docker exec -it service ls -l /opt/docker/resources/integrations | grep -P "\.json" | grep -Po '\w+ +\d+ +[\d:]+' | uniq -c | sort -n | tail -n1 | grep -Po '[A-Za-z].*')
    matches=$(docker exec -it service ls -l /opt/docker/resources/integrations | grep -v "${most_common_date}" | grep -P '\S+\.json(?!\.)')
    if [[ -z "${matches}" ]]; then
        echo "No edited descriptor files in the service container; skipping..."
        skip_review
    else
        echo "${matches}"
        pause_for_review "edited descriptor files (note that these need to be backed up, compared in case they are newer than the version being upgraded to, and potentially restored after upgrade)"
    fi

    #---> CHECK: duplicates in sudoers (host)

    # Count occurrences to see if there are any duplicates, and grep only lines with a count greater than 1
    matches=$(sudo cat /etc/sudoers | grep logichub | uniq -c | sed -E 's/^ +//' | grep -P '^[2-9]|1[0-9]')
    if [[ -z "${matches}" ]]; then
        echo "No duplicates found in sudoers; skipping..."
        skip_review
    else
        sudo cat /etc/sudoers | grep logichub
        pause_for_review "look for duplicates in sudoers. Older installers (and maybe current too?) often duplicate entries, so this is a cleanup task."
    fi

    #---> CHECK: custom descriptors or jar files in the scripts table (postgres)

    matches=$(docker exec -it postgres psql -P pager --u daemon lh -c "select kind, name from scripts where kind != '\"KindPython\"' order by kind, name;")
    if [[ "${matches}" == *"(0 rows)"* ]]; then
        echo "No descriptors or jar files in the scripts table; skipping..."
        skip_review
    else
        echo "${matches}"
        pause_for_review "Take note of descriptors and jar files in the scripts table, if any, just in case"
    fi

    #---> CHECK: dynamic.conf (host)

    docker exec -it service cat /opt/docker/data/service/conf/dynamic.conf
    pause_for_review "Showing for terminal history: dynamic.conf"

    #---> CHECK: integration connections (postgres)

    docker exec -it postgres psql -P pager --u daemon lh -c "select substring(cast(descriptor::json->'name' as varchar) from '\"(.+)\"') as \"Integration Name\", label, id, integration_id, substring(cast(descriptor::json->'runtimeEnvironment'->'descriptor'->'image' as varchar) from ':([^:]+?)\"$') as \"Docker tag\", substring(cast(descriptor::json->'runtimeEnvironment'->'descriptor'->'image' as varchar) from '\"(.+)\"') as \"Full Docker Image\" from integration_instances order by integration_id, label;"
    pause_for_review "Showing for terminal history: integration instances with image versions"

    printf "Complete.\n\n"
}

run_prep_commands
