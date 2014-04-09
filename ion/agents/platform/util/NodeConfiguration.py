from pyon.public import log

import yaml
import pprint as pp
import copy
import logging


class NodeConfiguration(object):
    
    def __init__(self):
        self.cfg = {}
        self.ports = {}
        self.attrs = {}

 

    def Open(self,platform_id,defaultFile,NodeConfigFile):
 
        self._platform_id = platform_id
        
        log.debug("%r: Open: %s %s", self._platform_id, defaultFile,NodeConfigFile)

 
        with open(defaultFile, 'r') as f:
                base_config_file = yaml.load(f)
                
        with open(NodeConfigFile, 'r') as f:
            node_config_file = yaml.load(f)


        self.cfg['meta_data']= copy.deepcopy(node_config_file["node_meta_data"])
    
        self.cfg['attributes']=copy.deepcopy(base_config_file["node_attributes"])
        
        self.attrs = copy.deepcopy(base_config_file["node_attributes"])
        
        
        
        
        port_dict = {}
        
        temp_port = {}
    
        for portKey in node_config_file["port_configs"]:
            port = node_config_file["port_configs"][portKey]
            port_name = port['port_name']
            temp_port['meta_data'] = copy.deepcopy(port)
            temp_port['attributes'] = copy.deepcopy(base_config_file["port_attributes"])

# go through and update the default port attributes for this port with specifics 
            for port_attr_key in temp_port['attributes']:
                port_attribute = temp_port['attributes'][port_attr_key]
                port_attribute['attr_id']=temp_port['meta_data']['port_oms_prefix']+' '+port_attribute['attr_id']
                port_attribute['ion_parameter_name']=temp_port['meta_data']['port_ion_prefix']+port_attribute['ion_parameter_name']
                self.attrs[portKey+'_'+port_attr_key]=port_attribute
            
            port_dict[port_name] = temp_port
                      
                      
                      
        self.cfg['port_dict'] = port_dict
 
        self._parmLookup = {}
        self._attrLookup = {}
                
         
        for attrKey,attr in self.attrs.iteritems():
            self._parmLookup[attr['attr_id']]=attr['ion_parameter_name']
            self._attrLookup[attr['ion_parameter_name']]=attr['attr_id']

    
    def GetNodeCommonName(self):
        return(self.cfg["meta_data"]['node_id_name'])
    
    def GetMetaData(self):
        return(self.cfg["meta_data"])


    def GetNodeAttrDict(self):
        return(self.attrs)
    
    def GetPortDict(self):
        return(self.cfg["port_dict"])
    
    
    def GetScaleFactorFromAttr(self,attr_id):
        for attrKey in self.cfg['attributes']:
            if attr_id == self.cfg['attributes'][attrKey]['attr_id'] :
                return self.cfg['attributes'][attrKey]['scale_factor']   
        return 1

    
    def GetParameterFromAttr(self,attr_id):
        if attr_id in self._parmLookup:
            return self._parmLookup[attr_id]
        else :
            return attr_id
        
    def GetAttrFromParameter(self,parameter_name):
        if parameter_name in self._attrLookup:
            return self._attrLookup[parameter_name]
        else :
            return parameter_name
   


if __name__ == '__main__':
   
    nodeConfig = NodeConfiguration()
  
    nodeConfig.Open('/tmp/node_config_files/default_node.yaml','/tmp/node_config_files/LPJBox_CI.yaml')
    
    pp.pprint(nodeConfig.cfg)
     
    pp.pprint(nodeConfig.GetScaleFactorFromAttr(self,'CIB_Board_State|750'))
     
    pp.pprint(nodeConfig.GetParameterFromAttr(self,'CIB_Board_State|750'))
     
    pp.pprint(nodeConfig.GetAttrFromParameter(self,'sec_node_cib_board_state'))
        