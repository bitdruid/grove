import ipaddress
import socket

import requests


def reachable(domain):
    try:
        response = requests.head("http://" + domain)
        return response.ok
    except (requests.exceptions.RequestException, TypeError):
        return False


def validate_domain(domain):
    """Validate if a domain is given."""
    try:
        ipaddress.ip_address(domain)
        return False
    except ValueError:
        domain_parts = domain.split(".")
        if len(domain_parts) > 1 and len(domain_parts[-1]) > 1:
            return True
        else:
            return False


def validate_ip(ip):
    """Validate if an IP address is given."""
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private:
            # print("Private IP address given.")
            return False
        return True
    except ValueError:
        return False


def validate_primary(user_input: str) -> bool:
    """
    Validate if a given user_input is a domain or IP address.

    parameters:
    - user_input (str): The domain or IP address to validate.

    returns:
    - bool: True if the user_input is a domain or IP address, False if not.
    """
    return validate_domain(user_input) or validate_ip(user_input)


def domain_to_ip(domain: str) -> str:
    try:
        if validate_ip(domain):
            return domain
        ip = socket.gethostbyname(domain)
        if validate_ip(ip):
            return ip
        else:
            return ""
    except socket.gaierror:
        return ""


def ip_to_domain(ip: str) -> str:
    try:
        if validate_domain(ip):
            return ip
        domain = socket.gethostbyaddr(ip)[0]
        if validate_domain(domain):
            return domain
        else:
            return ""
    except socket.herror:
        return ""


def get_primary(user_input: str) -> tuple:
    """
    Returns the primary domain and IP for a given domain or IP.

    parameters:
    - user_input (str): The domain or IP to check.

    returns:
    - tuple: [0] domain, [1] IP
    - bool: False if no domain or IP is given
    """
    if validate_domain(user_input):
        ip = domain_to_ip(user_input)
        return user_input, ip
    elif validate_ip(user_input):
        domain = ip_to_domain(user_input)
        return domain, user_input
    return "", ""
