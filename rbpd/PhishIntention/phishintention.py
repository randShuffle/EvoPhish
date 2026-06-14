import time
from datetime import datetime
import argparse
import os
import torch
import cv2
from configs import load_config
from modules.awl_detector import pred_rcnn, vis, find_element_type
from modules.logo_matching import check_domain_brand_inconsistency,check_domain_consistent
from modules.crp_classifier import credential_classifier_mixed, html_heuristic
from modules.crp_locator import crp_locator
from utils.web_utils import driver_loader
from tqdm import tqdm
import re
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import requests
import json

os.environ['KMP_DUPLICATE_LIB_OK']='True'

class PhishIntentionWrapper:
    _caller_prefix = "PhishIntentionWrapper"
    _DEVICE = 'cuda:1' if torch.cuda.is_available() else 'cpu'

    def __init__(self):
        self._load_config()

    def _load_config(self):
        self.AWL_MODEL, self.CRP_CLASSIFIER, self.CRP_LOCATOR_MODEL, self.SIAMESE_MODEL, \
            self.SIAMESE_THRE, self.LOGO_FEATS, self.LOGO_FILES, self.DOMAIN_MAP = load_config(self._DEVICE)
        print(f'Length of reference list = {len(self.LOGO_FEATS)}')

    '''PhishIntention'''
    @torch.no_grad()
    def test_orig_phishintention(self, url, screenshot_path):
        waive_crp_classifier = False
        phish_category = 0
        pred_target = None
        matched_domain = None
        siamese_conf = None
        awl_detect_time = 0
        logo_match_time = 0
        crp_class_time = 0
        crp_locator_time = 0
        # print("Entering PhishIntention")

        while True:

            ####################### Step1: Layout detector ##############################################
            start_time = time.time()
            pred_boxes, pred_classes, _ = pred_rcnn(im=screenshot_path, predictor=self.AWL_MODEL)
            awl_detect_time += time.time() - start_time

            if pred_boxes is not None:
                pred_boxes = pred_boxes.numpy()
                pred_classes = pred_classes.numpy()
            plotvis = vis(screenshot_path, pred_boxes, pred_classes)
            orivis = vis(screenshot_path,[],[])
            # If no element is reported
            if pred_boxes is None or len(pred_boxes) == 0:
                #print('No element is detected, reporte as benign')
                return phish_category,pred_target, matched_domain,siamese_conf,None,orivis,plotvis

            logo_pred_boxes, _ = find_element_type(pred_boxes, pred_classes, bbox_type='logo')
            if logo_pred_boxes is None or len(logo_pred_boxes) == 0:
                #print('No logo is detected, reporte as benign')
                return phish_category,pred_target, matched_domain,siamese_conf,None,orivis,plotvis

            #print('Entering siamese')

            ######################## Step2: Siamese (Logo matcher) ########################################
            start_time = time.time()
            phish_category,pred_target, matched_domain, matched_coord, siamese_conf,sim_file_name,top3_brandlist,top3_sim_path,top3_domainlist,cropped = check_domain_brand_inconsistency(logo_boxes=logo_pred_boxes,
                                                                                      domain_map=self.DOMAIN_MAP,
                                                                                      model = self.SIAMESE_MODEL,
                                                                                      logo_feat_list = self.LOGO_FEATS,
                                                                                      file_name_list = self.LOGO_FILES,
                                                                                      url=url,
                                                                                      shot_path=screenshot_path,
                                                                                      similarity_threshold=self.SIAMESE_THRE)
          

            logo_match_time += time.time() - start_time
    

            if phish_category!=2:
                # print('Did not match to any brand, report as benign')
                return phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,orivis,plotvis
                

            ######################## Step3: CRP classifier (if a target is reported) #################################
            # print('A target is reported by siamese, enter CRP classifier')
            if waive_crp_classifier:  # only run dynamic analysis ONCE
                break

            html_path = screenshot_path.replace(".png", ".txt")
            start_time = time.time()
            cre_pred = html_heuristic(html_path)
            if cre_pred == 1:  # if HTML heuristic report as nonCRP
                # CRP classifier
                cre_pred = credential_classifier_mixed(img=screenshot_path,
                                                         coords=pred_boxes,
                                                         types=pred_classes,
                                                         model=self.CRP_CLASSIFIER)
            crp_class_time += time.time() - start_time

            ######################## Step4: Dynamic analysis #################################
            if cre_pred == 1:
                phish_category = 4
                
                print('It is a Non-CRP page, enter dynamic analysis')
                # # load driver ONCE!
                driver = None
                try:
                    driver = driver_loader()
                    print('Finish loading webdriver')
                    # load chromedriver
                    url, screenshot_path, successful, process_time = crp_locator(url=url,
                                                                                screenshot_path=screenshot_path,
                                                                                cls_model=self.CRP_CLASSIFIER,
                                                                                ele_model=self.AWL_MODEL,
                                                                                login_model=self.CRP_LOCATOR_MODEL,
                                                                                driver=driver)
                    crp_locator_time += process_time
                    driver.quit()

                    waive_crp_classifier = True  # only run dynamic analysis ONCE

                    # If dynamic analysis did not reach a CRP
                    if not successful:
                        print('Dynamic analysis cannot find any link redirected to a CRP page, report as benign')
                        phish_category = 4
                        return phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,plotvis

                    else:  # dynamic analysis successfully found a CRP
                        print('Dynamic analysis found a CRP, go back to layout detector')            
                except:
                    return 4,pred_target, matched_domain,siamese_conf,sim_file_name,plotvis

                
                finally:
                    if driver is not None:
                        try:
                            driver.quit()
                        except Exception as e:
                            print(f"[WARN] Failed to quit driver cleanly: {e}")

            else:  # already a CRP page
                # print('Already a CRP, continue')
                break

        ######################## Step5: Return #################################
        if phish_category==2:
            print('Phishing is found!')
            # # Visualize, add annotations
            # cv2.putText(plotvis, "Target: {} with confidence {:.4f}".format(pred_target, siamese_conf),
            #             (int(matched_coord[0] + 20), int(matched_coord[1] + 20)),
            #             cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
         
            plotvis_pil = Image.fromarray(cv2.cvtColor(plotvis, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(plotvis_pil)

            font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            font = ImageFont.truetype(font_path, 32) 

       
            text = "Target: {} with confidence {:.4f}".format(pred_target, siamese_conf)

            draw.text((int(matched_coord[0] + 20), int(matched_coord[1] + 20)), text, font=font, fill=(0, 0, 0))

      
            plotvis = cv2.cvtColor(np.array(plotvis_pil), cv2.COLOR_RGB2BGR)

        return phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,orivis,plotvis


    @torch.no_grad()
    def test_orig_phishintention_vlm(self, url, screenshot_path):
        waive_crp_classifier = False
        phish_category = 0
        pred_target = None
        matched_domain = None
        siamese_conf = None
        awl_detect_time = 0
        logo_match_time = 0
        crp_class_time = 0
        crp_locator_time = 0
        # print("Entering PhishIntention")

        while True:

            ####################### Step1: Layout detector ##############################################
            start_time = time.time()
            pred_boxes, pred_classes, _ = pred_rcnn(im=screenshot_path, predictor=self.AWL_MODEL)
            awl_detect_time += time.time() - start_time

            if pred_boxes is not None:
                pred_boxes = pred_boxes.numpy()
                pred_classes = pred_classes.numpy()
            plotvis = vis(screenshot_path, pred_boxes, pred_classes)
            orivis = vis(screenshot_path,[],[])
            # If no element is reported
            if pred_boxes is None or len(pred_boxes) == 0:
                #print('No element is detected, reporte as benign')
                return phish_category,pred_target, matched_domain,siamese_conf,None,orivis,plotvis

            logo_pred_boxes, _ = find_element_type(pred_boxes, pred_classes, bbox_type='logo')
            if logo_pred_boxes is None or len(logo_pred_boxes) == 0:
                #print('No logo is detected, reporte as benign')
                return phish_category,pred_target, matched_domain,siamese_conf,None,orivis,plotvis

            #print('Entering siamese')

            ######################## Step2: Siamese (Logo matcher) ########################################
            start_time = time.time()
            phish_category,pred_target, matched_domain, matched_coord, siamese_conf,sim_file_name,top3_brandlist,top3_sim_path,top3_domainlist,cropped = check_domain_brand_inconsistency(logo_boxes=logo_pred_boxes,
                                                                                      domain_map=self.DOMAIN_MAP,
                                                                                      model = self.SIAMESE_MODEL,
                                                                                      logo_feat_list = self.LOGO_FEATS,
                                                                                      file_name_list = self.LOGO_FILES,
                                                                                      url=url,
                                                                                      shot_path=screenshot_path,
                                                                                      similarity_threshold=self.SIAMESE_THRE)
          

            logo_match_time += time.time() - start_time
            
            if (1):
                target_logo_path = screenshot_path.replace(".png", "_cropped.png")
                cropped.save(target_logo_path)
                logo_match_time += time.time() - start_time

           
                base_url = "http://localhost:7077"
                match_payload = {
                "target_logo_path": target_logo_path,
                "reference_logos": [
                    {"brand": top3_brandlist[0], "logo_path": top3_sim_path[0]},
                    {"brand": top3_brandlist[1], "logo_path": top3_sim_path[1]},
                    {"brand": top3_brandlist[2], "logo_path": top3_sim_path[2]},
                ],
            }

                brand2domains = {}
                for i in range(3):
                    brand2domains[top3_brandlist[i]] = top3_domainlist[i]
                    
                    
                try:
                    resp = requests.post(f"{base_url}/match", json=match_payload, timeout=120)
                    pred_target = resp.json()["matched_brand"]
                    if pred_target not in top3_brandlist:
                        phish_category = 0
                        pred_target = None
                        siamese_conf = 0
                    else:
                        if check_domain_consistent(url,brand2domains[pred_target]):
                            phish_category = 1
                        else:
                            phish_category = 2
                        
                    
                    
                except Exception as e:
                    print(f"[ERROR] {e}")
                finally:
                    if os.path.exists(target_logo_path):
                        os.remove(target_logo_path)

            if phish_category!=2:
                # print('Did not match to any brand, report as benign')
                return phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,orivis,plotvis
                

            ######################## Step3: CRP classifier (if a target is reported) #################################
            # print('A target is reported by siamese, enter CRP classifier')
            if waive_crp_classifier:  # only run dynamic analysis ONCE
                break

            html_path = screenshot_path.replace(".png", ".txt")
            start_time = time.time()
            cre_pred = html_heuristic(html_path)
            if cre_pred == 1:  # if HTML heuristic report as nonCRP
                # CRP classifier
                cre_pred = credential_classifier_mixed(img=screenshot_path,
                                                         coords=pred_boxes,
                                                         types=pred_classes,
                                                         model=self.CRP_CLASSIFIER)
            crp_class_time += time.time() - start_time

            ######################## Step4: Dynamic analysis #################################
            if cre_pred == 1:
          
                phish_category = 4

                
                print('It is a Non-CRP page, enter dynamic analysis')
                # # load driver ONCE!
                driver = None
                try:
                    driver = driver_loader()
                    print('Finish loading webdriver')
                    # load chromedriver
                    url, screenshot_path, successful, process_time = crp_locator(url=url,
                                                                                screenshot_path=screenshot_path,
                                                                                cls_model=self.CRP_CLASSIFIER,
                                                                                ele_model=self.AWL_MODEL,
                                                                                login_model=self.CRP_LOCATOR_MODEL,
                                                                                driver=driver)
                    crp_locator_time += process_time
                    driver.quit()

                    waive_crp_classifier = True  # only run dynamic analysis ONCE

                    # If dynamic analysis did not reach a CRP
                    if not successful:
                        print('Dynamic analysis cannot find any link redirected to a CRP page, report as benign')
                        phish_category = 4
                        return phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,plotvis

                    else:  # dynamic analysis successfully found a CRP
                        print('Dynamic analysis found a CRP, go back to layout detector')            
                except:
                    return 4,pred_target, matched_domain,siamese_conf,sim_file_name,plotvis

                
                finally:
                    if driver is not None:
                        try:
                            driver.quit()
                        except Exception as e:
                            print(f"[WARN] Failed to quit driver cleanly: {e}")

            else:  # already a CRP page
                # print('Already a CRP, continue')
                break

        ######################## Step5: Return #################################
        if phish_category==2:
            print('Phishing is found!')
            # # Visualize, add annotations
            # cv2.putText(plotvis, "Target: {} with confidence {:.4f}".format(pred_target, siamese_conf),
            #             (int(matched_coord[0] + 20), int(matched_coord[1] + 20)),
            #             cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
       
            plotvis_pil = Image.fromarray(cv2.cvtColor(plotvis, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(plotvis_pil)

    
            font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            font = ImageFont.truetype(font_path, 32)

            text = "Target: {} with confidence {:.4f}".format(pred_target, siamese_conf)

        
            draw.text((int(matched_coord[0] + 20), int(matched_coord[1] + 20)), text, font=font, fill=(0, 0, 0))

        
            plotvis = cv2.cvtColor(np.array(plotvis_pil), cv2.COLOR_RGB2BGR)

        return phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,orivis,plotvis

   