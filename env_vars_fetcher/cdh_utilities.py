try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    from sshtunnel.sshtunnel import SSHTunnelForwarder
from cm_api.api_client import ApiResource, ApiException
from cm_api.endpoints.services import ApiService, ApiServiceSetupInfo
import paramiko
import json
import yaml
import requests
import subprocess
import zipfile
import shutil
import os
import logger
import base64

class CdhConfExtractor(object):

    def __init__(self, config_filename=None):
        self._logger = logger.get_info_logger(__name__)
        self.config_filename = config_filename if config_filename else 'fetcher_config.yml'
        config = self._load_config_yaml(self.config_filename)
        self._hostname = config['machines']['cdh-launcher']['hostname']
        self._hostport = config['machines']['cdh-launcher']['hostport']
        self._username = config['machines']['cdh-launcher']['username']
        self._key_filename = config['machines']['cdh-launcher']['key_filename']
        self._key = os.path.expanduser(self._key_filename)
        self._key_password = config['machines']['cdh-launcher']['key_password']
        self._is_openstack = config['is_openstack_env']
        self._is_kerberos = config['is_kerberos']
        self._cdh_manager_ip = config['machines']['cdh-manager']['ip']
        self._cdh_manager_user = config['machines']['cdh-manager']['user']
        self._cdh_manager_password = config['machines']['cdh-manager']['password']

    def __enter__(self):
        extractor = self
        try:
            self._logger.info('Creating tunnel to CDH-Manager.')
            extractor.create_tunnel_to_cdh_manager()
            extractor.start_cdh_manager_tunneling()
            self._logger.info('Tunnel to CDH-Manager has been created.')
            return extractor
        except Exception as exc:
            self._logger.error('Cannot creating tunnel to CDH-Manager machine.')
            raise exc

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.stop_cdh_manager_tunneling()
            self._logger.info('Tunelling to CDH-Manager stopped.')
        except Exception as exc:
            self._logger.error('Cannot close tunnel to CDH-Manager machine.')
            raise exc

    # Cdh launcher methods
    def create_ssh_connection_to_cdh(self):
        try:
            self._logger.info('Creating connection to CDH-launcher.')
            self.ssh_connection = paramiko.SSHClient()
            self.ssh_connection.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_connection.connect(self._hostname, username=self._username, key_filename=self._key, password=self._key_password)
            self._logger.info('Connection to CDH-launcher established.')
        except Exception as exc:
            self._logger.error('Cannot creating connection to CDH-launcher machine. Check your settings '
                               'in fetcher_config.yml file.')
            raise exc

    def close_connection_to_cdh(self):
        try:
            self.ssh_connection.close()
            self._logger.info('Connection to CDH-launcher closed.')
        except Exception as exc:
            self._logger.error('Cannot close connection to the CDH-launcher machine.')
            raise exc

    def ssh_call_command(self, command, subcommands=None):
        self._logger.info('Calling remote command: "{0}" with subcommands "{1}"'.format(command, subcommands))
        ssh_in, ssh_out, ssh_err = self.ssh_connection.exec_command(command, get_pty=True)
        if subcommands != None:
            for subcommand in subcommands:
                ssh_in.write(subcommand + '\n')
                ssh_in.flush()
        return ssh_out.read() if ssh_out is not None else ssh_err.read()

    def extract_cdh_manager_host(self):
        self._logger.info('Extracting CDH-Manager address.')
        if self._cdh_manager_ip is None:
            self.create_ssh_connection_to_cdh()
            if self._is_openstack.lower() == 'true':
                ansible_ini = self.ssh_call_command('cat ansible-cdh/platform-ansible/inventory/cdh')
            else:
                ansible_ini = self.ssh_call_command('cat ansible-cdh/inventory/cdh')
            self._cdh_manager_ip = self._get_host_ip('cdh-manager', ansible_ini)
            self.close_connection_to_cdh()
        self._logger.info('CDH-Manager adress extracted: {}'.format(self._cdh_manager_ip))
        return self._cdh_manager_ip

    # Cdh manager methods
    def create_tunnel_to_cdh_manager(self, local_bind_address='localhost', local_bind_port=7180, remote_bind_port=7180):
        self._local_bind_address = local_bind_address
        self._local_bind_port = local_bind_port
        self.cdh_manager_tunnel = SSHTunnelForwarder(
            (self._hostname, self._hostport),
            ssh_username=self._username,
            local_bind_address=(local_bind_address, local_bind_port),
            remote_bind_address=(self.extract_cdh_manager_host(), remote_bind_port),
            ssh_private_key_password=self._key_password,
            ssh_private_key=self._key
        )

    def start_cdh_manager_tunneling(self):
        try:
            self.cdh_manager_tunnel.start()
        except Exception as e:
            self._logger.error('Cannot start tunnel: ' + e.message)

    def stop_cdh_manager_tunneling(self):
        try:
            self.cdh_manager_tunnel.stop()
        except Exception as e:
            self._logger.error('Cannot stop tunnel: ' + e.message)

    def extract_cdh_manager_details(self, settings):
        for host in settings['hosts']:
            if 'cdh-manager' in host['hostname']:
                return host

    def extract_master_nodes_info(self, settings):
        master_nodes = []
        for host in settings['hosts']:
            if 'cdh-master' in host['hostname']:
                master_nodes.append(host)
        return master_nodes

    def extract_service_namenode(self, service_name, role_name, settings):
        hdfs_service = self._find_item_by_attr_value(service_name, 'name', settings['clusters'][0]['services'])
        hdfs_namenode = self._find_item_by_attr_value(role_name, 'name', hdfs_service['roles'])
        host_id = hdfs_namenode['hostRef']['hostId']
        return self._find_item_by_attr_value(host_id, 'hostId', settings['hosts'])['hostname']

    def get_client_config_for_service(self, service_name):
        result = requests.get('http://{0}:{1}/api/v10/clusters/CDH-cluster/services/{2}/clientConfig'.format(self._local_bind_address, self._local_bind_port, service_name))
        return base64.standard_b64encode(result.content);

    def generate_keytab(self, principal_name):
        self._logger.info('Generating keytab for {} principal.'.format(principal_name))
        self.create_ssh_connection_to_cdh()
        sftp = self.ssh_connection.open_sftp()
        sftp.put('utils/generate_keytab_script.sh', '/tmp/generate_keytab_script.sh')
        self.ssh_call_command('scp -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no /tmp/generate_keytab_script.sh {0}:/tmp/'.format(self._cdh_manager_ip))
        self.ssh_call_command('ssh -t {0} -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "chmod 700 /tmp/generate_keytab_script.sh"'.format(self._cdh_manager_ip))
        keytab_hash = self.ssh_call_command('ssh -t {0} -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "/tmp/generate_keytab_script.sh {1}"'
                                            .format(self._cdh_manager_ip, principal_name))
        self.close_connection_to_cdh()
        lines = keytab_hash.splitlines()
        self._logger.info('Keytab for {} principal has been generated.'.format(principal_name))
        return '"{}"'.format(''.join(lines[2:-2]))

    def generate_base64_for_file(self, file_path, hostname):
        self._logger.info('Generating base64 for {} file.'.format(file_path))
        self.create_ssh_connection_to_cdh()
        base64_file_hash = self.ssh_call_command('ssh -t {0} -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no "base64 {1}"'.format(hostname, file_path))
        self.close_connection_to_cdh()
        lines = base64_file_hash.splitlines()
        self._logger.info('Base64 hash for {0} file on {1} machine has been generated.'.format(file_path, hostname))
        return '"{}"'.format(''.join(lines[2:-2]))

    def get_all_deployments_conf(self, cdh_manager_username='admin', cdh_manager_password='admin'):
        result = {}
        deployments_settings = json.loads(requests.get('http://' + self._local_bind_address + ':'
                                                       + str(self._local_bind_port) + '/api/v10/cm/deployment',
                                                    auth=(cdh_manager_username, cdh_manager_password)).content)
        result['cloudera_manager_internal_host'] = self.extract_cdh_manager_details(deployments_settings)['hostname']

        if self._is_kerberos.lower() == 'true':
            result['kerberos_host'] = result['cloudera_manager_internal_host']
            result['hdfs_keytab_value'] = self.generate_keytab('hdfs')
            result['vcap_keytab_value'] = self.generate_keytab('vcap')
            result['krb5_base64'] = self.generate_base64_for_file('/etc/krb5.conf', self._cdh_manager_ip)
            result['sentry_keytab_value'] = self.generate_keytab('hive/sys')
            result['auth_gateway_profile'] = 'cloud,zookeeper-auth-gateway,hdfs-auth-gateway,sentry-auth-gateway'
        else:
            result['hdfs_keytab_value'] = "''"
            result['vcap_keytab_value'] = '""'
            result['krb5_base64'] = '""'
            result['sentry_keytab_value'] = "''"
            result['auth_gateway_profile'] = 'cloud,zookeeper-auth-gateway,hdfs-auth-gateway'

        master_nodes = self.extract_master_nodes_info(deployments_settings)
        for i, node in enumerate(master_nodes):
            result['master_node_host_' + str(i+1)] = node['hostname']
        result['namenode_internal_host'] = self.extract_service_namenode('HDFS', 'HDFS-NAMENODE', deployments_settings)
        result['hue_node'] = self.extract_service_namenode('HUE', 'HUE-HUE_SERVER', deployments_settings)
        result['import_hadoop_conf_hdfs'] = self.get_client_config_for_service('HDFS')
        result['import_hadoop_conf_hbase'] = self.get_client_config_for_service('HBASE')
        result['import_hadoop_conf_yarn'] = self.get_client_config_for_service('YARN')
        
        cdh_host = self.extract_cdh_manager_host()
        helper = CdhApiHelper(ApiResource(cdh_host, username=self._cdh_manager_user, password=self._cdh_manager_password, version=9))
        sentry_service = helper.get_sentry_service_from_cdh()
        result['sentry_port'] = helper.get_sentry_port(sentry_service)
        result['sentry_address'] = helper.get_sentry_host(sentry_service)

        return result

    # helpful methods

    def _find_item_by_attr_value(self, attr_value, attr_name, array_with_dicts):
        return next(item for item in array_with_dicts if item[attr_name] == attr_value)

    def _get_host_ip(self, host, ansible_ini):
        host_info = []
        for line in ansible_ini.split('\n'):
            if host in line:
                host_info.append(line.strip())
        return host_info[host_info.index('[' + host + ']') + 1].split(' ')[1].split('=')[1]

    def _load_config_yaml(self, filename):
        with open(filename, 'r') as stream:
            return yaml.load(stream)

class CdhApiHelper(object):

    def __init__(self, cdhApi):
        self.cdhApi = cdhApi

    def get_sentry_service_from_cdh(self):
        cluster = self.cdhApi.get_all_clusters()[0]
        return next(service for service in cluster.get_all_services() if service.type == 'SENTRY')

    def get_sentry_host(self, sentry):
        sentry_id = sentry.get_all_roles()[0].hostRef.hostId
        return self.cdhApi.get_host(sentry_id).hostname

    def get_sentry_port(self, sentry):
        sentry_config = sentry.get_all_roles()[0].get_config('full')
        for config_entry in sentry_config:
            if "port" in config_entry:
                port = sentry_config[config_entry].value or sentry_config[config_entry].default
        return port
