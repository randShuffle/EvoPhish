# Global configuration
import subprocess
import yaml
from modules.awl_detector import config_rcnn,config_rcnn_pytorch
from modules.crp_classifier import credential_config
# from modules.logo_matching import siamese_model_config, ocr_model_config, cache_reference_list
from modules.logo_matching import cache_reference_list
import os
import numpy as np
import pickle
import logging
import torch
from collections import OrderedDict
from phishpedia_models import KNOWN_MODELS,MobileNetV2


# def load_model_weights(num_classes: int, weights_path: str):
#     '''
#     :param num_classes: number of protected brands
#     :param weights_path: siamese weights
#     :return model: siamese model
#     '''
#     # Initialize model
#     model = KNOWN_MODELS["BiT-M-R50x1"](head_size=num_classes, zero_head=True)

#     # Load weights
#     weights = torch.load(weights_path, map_location='cpu',weights_only=False)
#     weights = weights['model'] if 'model' in weights.keys() else weights
#     new_state_dict = OrderedDict()
#     for k, v in weights.items():
#         if 'module.' in k:
#             name = k.split('module.')[1]
#         else:
#             name = k
#         new_state_dict[name] = v

#     model.load_state_dict(new_state_dict)
#     model.eval()
#     return model


def load_model_weights(num_classes: int, weights_path: str):
    
    if "mobilenet" in weights_path:
        model = MobileNetV2(num_classes=num_classes)
        print("mobilenetv2 loaded")
    else:
        # Initialize model
        model = KNOWN_MODELS["BiT-M-R50x1"](head_size=num_classes, zero_head=True)
        print("resnetv2 loaded")

    # Load weights
    weights = torch.load(weights_path, map_location='cpu',weights_only=False)
    weights = weights['model'] if 'model' in weights.keys() else weights

    new_state_dict = OrderedDict()
    for k, v in weights.items():
        if 'module.' in k:
            name = k.split('module.')[1]
        else:
            name = k
        new_state_dict[name] = v

    model.load_state_dict(new_state_dict)
    model.eval()
    return model


def load_domain_map(domain_map_path):
    try:
        with open(domain_map_path, 'rb') as handle:
            return pickle.load(handle)
    except Exception as e:
        logging.error(f"Failed to load domain map: {e}")
        return None

def get_absolute_path(relative_path):
    base_path = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(base_path, relative_path))

def load_config(_DEVICE,reload_targetlist=False):

    with open(os.path.join(os.path.dirname(__file__), 'configs/configs.yaml')) as file:
        configs = yaml.load(file, Loader=yaml.FullLoader)

    # Iterate through the configuration and update paths
    for section, settings in configs.items():
        for key, value in settings.items():
            if 'PATH' in key and isinstance(value, str):  # Check if the key indicates a path
                absolute_path = get_absolute_path(value)
                configs[section][key] = absolute_path


    # AWL_MODEL = config_rcnn(_DEVICE,cfg_path=configs['AWL_MODEL']['CFG_PATH'],
    #                                     weights_path=configs['AWL_MODEL']['WEIGHTS_PATH'],
    #                                     conf_threshold=configs['AWL_MODEL']['DETECT_THRE'])
    
    ELE_WEIGHTS_PATH = configs['ELE_MODEL']['WEIGHTS_PATH']
    AWL_MODEL = config_rcnn_pytorch(ELE_WEIGHTS_PATH)
    AWL_MODEL = AWL_MODEL.to(_DEVICE)
    print('RCNN model loaded')

    CRP_CLASSIFIER = credential_config(_DEVICE,
                                    checkpoint=configs['CRP_CLASSIFIER']['WEIGHTS_PATH'],
                                    model_type=configs['CRP_CLASSIFIER']['MODEL_TYPE'])

  
    CRP_LOCATOR_MODEL = config_rcnn(_DEVICE,
                                cfg_path=configs['CRP_LOCATOR']['CFG_PATH'],
                                weights_path=configs['CRP_LOCATOR']['WEIGHTS_PATH'],
                                conf_threshold=configs['CRP_LOCATOR']['DETECT_THRE'])


    # siamese model
    SIAMESE_THRE = configs['SIAMESE_MODEL']['MATCH_THRE']

    print('Load protected logo list')
    targetlist_zip_path = configs['SIAMESE_MODEL']['TARGETLIST_PATH']
    targetlist_dir = os.path.dirname(targetlist_zip_path)
    zip_file_name = os.path.basename(targetlist_zip_path)
    targetlist_folder = zip_file_name.split('.zip')[0]
    full_targetlist_folder_dir = os.path.join(targetlist_dir, targetlist_folder)

    # SIAMESE_MODEL = siamese_model_config(_DEVICE,num_classes=configs['SIAMESE_MODEL']['NUM_CLASSES'],
    #                                      weights_path=configs['SIAMESE_MODEL']['WEIGHTS_PATH'])

    # #SIAMESE_MODEL = SIAMESE_MODEL.to(_DEVICE)
    # OCR_MODEL = ocr_model_config(_DEVICE,weights_path = configs['SIAMESE_MODEL']['OCR_WEIGHTS_PATH'])
    # #OCR_MODEL = OCR_MODEL.to(_DEVICE)
    # if reload_targetlist or (not os.path.exists(os.path.join(os.path.dirname(__file__), 'LOGO_FEATS.npy'))):
    #     LOGO_FEATS, LOGO_FILES = cache_reference_list(model=SIAMESE_MODEL,
    #                                                   ocr_model=OCR_MODEL,
    #                                                   targetlist_path=full_targetlist_folder_dir)
    #     print('Finish loading protected logo list')
    #     np.save(os.path.join(os.path.dirname(__file__),'LOGO_FEATS.npy'), LOGO_FEATS)
    #     np.save(os.path.join(os.path.dirname(__file__),'LOGO_FILES.npy'), LOGO_FILES)

    # else:
    #     LOGO_FEATS, LOGO_FILES = np.load(os.path.join(os.path.dirname(__file__),'LOGO_FEATS.npy')), \
    #                              np.load(os.path.join(os.path.dirname(__file__),'LOGO_FILES.npy'))
    
    # siamese model
    SIAMESE_THRE = configs['SIAMESE_MODEL']['MATCH_THRE']

    targetlist_dir = configs['SIAMESE_MODEL']['TARGETLIST_PATH']

    
    SIAMESE_WEIGHTS_PATH = configs['SIAMESE_MODEL']['WEIGHTS_PATH']
    logging.info("Loading deep siamese model from {}".format(SIAMESE_WEIGHTS_PATH))
    SIAMESE_MODEL = load_model_weights(num_classes=configs['SIAMESE_MODEL']['NUM_CLASSES'],
                                        weights_path=configs['SIAMESE_MODEL']['WEIGHTS_PATH'])

    SIAMESE_MODEL = SIAMESE_MODEL.to(_DEVICE)
    if reload_targetlist or (not os.path.exists(os.path.join(os.path.dirname(__file__), 'LOGO_FEATS.npy'))):
        logging.info('No cached reference embeddings are found, trying to predict them')
        LOGO_FEATS, LOGO_FILES = cache_reference_list(model=SIAMESE_MODEL,
                                                      targetlist_path=targetlist_dir)
        
        logging.info('Finish predicting the reference logos embeddings')
        np.save(os.path.join(os.path.dirname(__file__),'LOGO_FEATS.npy'), LOGO_FEATS)
        np.save(os.path.join(os.path.dirname(__file__),'LOGO_FILES.npy'), LOGO_FILES)


    logging.info('Loading cached reference logos embeddings')
    LOGO_FEATS, LOGO_FILES = np.load(os.path.join(os.path.dirname(__file__),'LOGO_FEATS.npy')), \
                             np.load(os.path.join(os.path.dirname(__file__),'LOGO_FILES.npy'))
    
    

    DOMAIN_MAP_PATH = configs['SIAMESE_MODEL']['DOMAIN_MAP_PATH']
    DOMAIN_MAP = load_domain_map(DOMAIN_MAP_PATH)

    return AWL_MODEL, CRP_CLASSIFIER, CRP_LOCATOR_MODEL, SIAMESE_MODEL, SIAMESE_THRE, LOGO_FEATS, LOGO_FILES, DOMAIN_MAP