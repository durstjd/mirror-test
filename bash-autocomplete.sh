#!/bin/bash
# Improved bash completion for mirror-test based on arsync approach

_mirror_test_completions() {
    local cur prev opts base_commands distributions
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    # Base commands
    base_commands="all gui cli refresh logs dockerfile cleanup list variables validate help"
    
    # Options
    opts="--config --port --verbose --quiet --timeout --no-cleanup --version --help -v -q -h"
    
    # Get distributions from config file using Python (refreshed on every run)
    distributions=""
    config_file="$HOME/.config/mirror-test/mirror-test.yaml"
    if [ -f "$config_file" ]; then
        distributions=$(python3 -c "
import yaml
import sys
try:
    with open('$config_file', 'r') as f:
        config = yaml.safe_load(f)
    if 'distributions' in config:
        print(' '.join(config['distributions'].keys()))
    else:
        # Fallback: look for top-level keys that aren't system sections
        system_keys = {'variables', 'package-managers'}
        dist_keys = [k for k in config.keys() if k not in system_keys]
        print(' '.join(dist_keys))
except:
    pass
" 2>/dev/null)
    fi
    
    # Use default distributions if none found
    if [ -z "$distributions" ]; then
        distributions="debian ubuntu rocky almalinux fedora centos opensuse alpine"
    fi
    
    # Handle different completion contexts
    case "${prev}" in
        mirror-test)
            # First argument - show commands, distributions, and options
            COMPREPLY=( $(compgen -W "${base_commands} ${distributions} ${opts}" -- ${cur}) )
            return 0
            ;;
        
        --config)
            # Complete with yaml files
            COMPREPLY=( $(compgen -f -X '!*.yaml' -- ${cur}) )
            COMPREPLY+=( $(compgen -f -X '!*.yml' -- ${cur}) )
            return 0
            ;;
        
        --port)
            # Suggest common ports
            COMPREPLY=( $(compgen -W "8080 8081 8082 3000 5000 9090" -- ${cur}) )
            return 0
            ;;
        
        --timeout)
            # Suggest common timeout values
            COMPREPLY=( $(compgen -W "300 600 900 1200 1800" -- ${cur}) )
            return 0
            ;;
        
        logs|dockerfile)
            # These commands need a distribution name
            COMPREPLY=( $(compgen -W "${distributions}" -- ${cur}) )
            return 0
            ;;
        
        gui|cli|cleanup|all|list|variables|validate|help)
            # These commands don't take additional arguments, suggest options
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
        
        -*)
            # After an option, complete with options
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
        
        *)
            # Check if we're completing distribution names
            local cmd_index=1
            local found_command=false
            
            # Find if a command has been specified
            for (( i=1; i < ${#COMP_WORDS[@]}-1; i++ )); do
                if [[ " ${base_commands} " =~ " ${COMP_WORDS[$i]} " ]]; then
                    found_command=true
                    break
                fi
            done
            
            if [[ "$found_command" == false ]]; then
                # No command yet, might be listing distributions to test
                # Allow multiple distribution names
                COMPREPLY=( $(compgen -W "${distributions} ${opts}" -- ${cur}) )
            else
                # Command already specified, show options
                COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            fi
            return 0
            ;;
    esac
}

# Register the completion function
complete -F _mirror_test_completions mirror-test

# Also register for common aliases
complete -F _mirror_test_completions mt
complete -F _mirror_test_completions mirror_test
