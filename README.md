platform-appstack
=================

Cloud Foundry platform definition files to be used with https://github.com/trustedanalytics/cloudfoundry-mkappstack.

## Preparation

Install necessary Python libraries:
```
sudo apt-get install python-pip
sudo pip install jinja2 pyyaml
```

Edit template_variables.yml file.
You should obtain missing values from the sources listed below.

1) EC2 instance where platform will be deployed

From:
```
~/workspace/deployments/docker-services-boshworkspace/deployments/docker-aws-vpc.yml
```
obtain:  
* nats_ip (meta/nats/machines)  

From:
```
~/workspace/deployments/cf-boshworkspace/deployments/cf-aws-tiny.yml
```
obtain:  
* cf_admin_password (meta/admin_secret)  
* cf_admin_client_password (meta/secret)  
* apps_domain (meta/app_domains)  
* developer_console_password (meta/secret)  
* email_address (meta/login_smtp/senderEmail)  
* run_domain (meta/domain)  
* smtp_pass (meta/login_smtp/password)  
* smtp_user (meta/login_smtp/user)  

2) From Cloudera Manager UI, obtain:
* gearpump_webui_server_host (Status/Gearpump/WebUI Server/Host)
* master_node_ip_1 (Zookeeper/Instances)
* master_node_ip_2 (Zookeeper/Instances)
* master_node_ip_3 (Zookeeper/Instances)
* namenode_internal_host (HDFS, Namenode summary)
* cloudera_manager_internal_host (Hosts, search for Cloudera)
* kerberos_host - the same as cloudera_manager_internal_host

3) Other sources:
* import_hadoop_conf_`<broker_name>`:  
Following instructions in [Hadoop Admin Tools](https://github.com/trustedanalytics/hadoop-admin-tools) repository, obtain JSON values for: import_hadoop_conf_hbase, import_hadoop_conf_hdfs, import_hadoop_conf_yarn.
* atk_client_name:
The default value for this field is `atk-client` and may be left unchanged.
* atk_client pass:
It was generated during step [Add UAA clients](https://github.com/trustedanalytics/platform-wiki/wiki/Platform-Deployment-Procedure:-bosh-deployment#add-uaa-clients) and you should remember it or have it written down.

## Usage
1. Generate settings.yml: `python generate_template.py`
1. Copy settings.yml and appstack.yml to cloudfoundry-mkappstack folder.
1. Please, check the names format of zipped artifacts in artifacts directory.

If they contain versions and are in the following format:
`<appname>-<version>.zip`
(for example: app-launcher-helper-0.4.5.zip) 
* Copy versions.yml file to cloudfoundry-mkappstack folder.
* Verify if versions in versions.yml are the same as versions in zipped artifacts file names. 
* If you encounter differences, update versions in versions.yml file so they are the same as in the zipped artifact file names.

If they do not contain version and are in the following format:
`<appname>.zip` 
(for example: app-launcher-helper.zip) 
* No additional actions are required. Please proceed with further instructions.

Follow further instructions from [Platform Deployment Procedure](https://github.com/trustedanalytics/platform-wiki/wiki/Platform-Deployment-Procedure%3A-bosh-deployment) to deploy the platform applications and brokers
