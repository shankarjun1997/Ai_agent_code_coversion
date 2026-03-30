"<E>,Procedure          SP_ONEF_EWO_MATERIALS as 
</E><E>,
</E><E>,V_EWO_MATERIAL_STG1 NUMBER;
</E><E>,V_EWO_MATERIAL_STG2 NUMBER;
</E><E>,
</E><E>,
</E><E>,V_EXCEPTION EXCEPTION;
</E><E>,V_SESS_INTF_ID NUMBER;
</E><E>,V_SESS_INST_ID NUMBER;
</E><E>,V_ERR_CODE NUMBER;
</E><E>,V_ERR_MSG VARCHAR2(500);
</E><E>,
</E><E>,
</E><E>,
</E><E>,Begin
</E><E>,
</E><E>,DBMS_OUTPUT.PUT_LINE(&apos;SP_ONEF_EWO_MATERIALS Report Refresh Started - &apos;||SYSTIMESTAMP);
</E><E>,
</E><E>,	/* Logging Step */
</E><E>,
</E><E>,	SELECT ONEF_INTF_ID, VNADSPRD.ONEF_SESS_INST_ID.NEXTVAL INTO V_SESS_INTF_ID, V_SESS_INST_ID FROM VNADSPRD.ONEF_INTF_CTRL_TBL WHERE ONEF_INTF_ID = 57;
</E><E>,	DBMS_OUTPUT.PUT_LINE(&apos;V_SESS_INTF_ID : &apos;||V_SESS_INTF_ID||&apos;, V_SESS_INST_ID : &apos;||V_SESS_INST_ID);
</E><E>,
</E><E>,	INSERT INTO VNADSPRD.ONEF_SESS_STATUS_LOGS
</E><E>,	(
</E><E>,		ONEF_SESS_INTF_ID,
</E><E>,		ONEF_SESS_INTF_INST_ID,
</E><E>,		ONEF_SESS_INTF_RUN_MODE,
</E><E>,		ONEF_SESS_START_DATE,
</E><E>,		ONEF_SESS_RUN_MON,
</E><E>,		ONEF_SESS_RUN_YEAR,
</E><E>,		ONEF_SESS_START_TS,
</E><E>,		ONEF_SESS_LOG_MSG
</E><E>,	) 
</E><E>,	SELECT 
</E><E>,		V_SESS_INTF_ID ONEF_SESS_INTF_ID,
</E><E>,		V_SESS_INST_ID ONEF_SESS_INTF_INST_ID,
</E><E>,		&apos;Running&apos; ONEF_SESS_INTF_RUN_MODE,
</E><E>,		TRUNC(SYSDATE) ONEF_SESS_START_DATE,
</E><E>,		TO_CHAR(TRUNC(SYSDATE), &apos;MON&apos;) ONEF_SESS_RUN_MON,
</E><E>,		TO_CHAR(TRUNC(SYSDATE), &apos;YYYY&apos;) ONEF_SESS_RUN_YEAR,
</E><E>,		SYSTIMESTAMP ONEF_SESS_START_TS,
</E><E>,		&apos;&apos; ONEF_SESS_LOG_MSG
</E><E>,	FROM 
</E><E>,		DUAL;
</E><E>,	COMMIT;
</E><E>,
</E><E>,
</E><E>,Execute immediate &apos;Truncate table Vnadsprd.onef_Materials_EWOS_STG drop storage&apos;;
</E><E>,
</E><E>, Insert into Vnadsprd.onef_Materials_EWOS_STG
</E><E>,select  distinct market_name, COMPONENT_NFID,AFE,ONEFIBER_SUBTYPE,STATUS, sysdate Last_Refreshed_Ts
</E><E>,from vnadsprd.wfm_nf_3gis_order_details where COMPONENT_TYPE=&apos;EWO&apos;
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,
</E><E>,
</E><E>,Execute immediate &apos;Truncate table Vnadsprd.Onef_Materials_EWO_As_Bulit_Comp_DT drop storage&apos;;
</E><E>,
</E><E>,insert into Vnadsprd.Onef_Materials_EWO_As_Bulit_Comp_DT
</E><E>,select NFID,TASK_NAME,LAST_MODIFIED_TIME AS_BUILT_COMP_DT,row_number()over(partition by NFID order by LAST_MODIFIED_TIME desc)rnk ,sysdate Last_Refreshed_Ts
</E><E>,from VNADSPRD.WFM_NF_3GIS_TASK_DETAIL S where 1=1 
</E><E>,and task_name=&apos;AsBuilt Design Review/Approve&apos; and task_status=&apos;COMPLETED&apos;
</E><E>,;
</E><E>,
</E><E>,Execute immediate &apos;Truncate table Vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT drop storage &apos;;
</E><E>,
</E><E>,insert into Vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT
</E><E>,select NFID,TASK_NAME,Trunc(LAST_MODIFIED_TIME) NTP_ACCEPT_DT,row_number()over(partition by NFID order by LAST_MODIFIED_TIME desc)rnk ,sysdate Last_Refreshed_Ts
</E><E>,from VNADSPRD.WFM_NF_3GIS_TASK_DETAIL S where 1=1 
</E><E>,and task_name=&apos;NTP Vendor Accept&apos; and task_status=&apos;CREATED&apos;
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,Execute immediate &apos;Truncate table Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY drop storage &apos;;
</E><E>,
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE,EWO, NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT, FOOTAGE, MILES,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type,EWO.AFE,COMPONENT_NFID EWO, NTP_ACCEPT_DT,trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;SPAN&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.span@icgspdr_3gis  Span
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=Span.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1 
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT 
</E><E>,;
</E><E>,
</E><E>,commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT, FOOTAGE, MILES,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type,EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Fibercable&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.fibercable@icgspdr_3gis  Fbr
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=Fbr.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1 
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT, FOOTAGE, MILES,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Slack Loop&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.slackloop@icgspdr_3gis  Slack
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=Slack.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT, FOOTAGE, MILES,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Span Unit&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.span_unit@icgspdr_3gis  Su
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=Su.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Equipment&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.fiberequipment@icgspdr_3gis  eqp
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=eqp.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;FDH&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.FDH@icgspdr_3gis  FDH
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=fdh.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;FDA&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.FDA@icgspdr_3gis  FDA
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=fda.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Splice Closure&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.spliceclosure@icgspdr_3gis  SPL
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=spl.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Structure&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.structure@icgspdr_3gis  STR
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=STR.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO,NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Building&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.building@icgspdr_3gis  bld
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=bld.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE,COMPONENT_NFID EWO, NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Building Footprint&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.buildingfootprint@icgspdr_3gis  bfp
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=bfp.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE, COMPONENT_NFID EWO, NTP_ACCEPT_DT,trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Building Outline&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.buildingoutline@icgspdr_3gis  bol
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=bol.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,insert into Vnadsprd.ONEF_EWO_MATERIALS_SUMMARY
</E><E>,(DIRECTOR, REGION, MARKET_NAME, CONTRACT_TYPE, AFE, EWO,NTP_APPROVED_DT, AS_BUILT_DATE,FEATURE_TYPE, FQ_CNT--, FOOTAGE, MILES
</E><E>,,LAST_REFRESHED_TS,EWO_STATUS, NTP_ESTIMATE, NTP_BEST_VIEW_AMOUNT)
</E><E>,select Director,Dir.Region,EWO.Market_Name,ONEFIBER_SUBTYPE Contract_Type, EWO.AFE,COMPONENT_NFID EWO, NTP_ACCEPT_DT, trunc(AS_BUILT_COMP_DT) AS_BUILT_DATE
</E><E>,,&apos;Pole&apos; Feature_TYPE,Count(FQN_ID) FQ_CNT--, sum(calculatedlength)Footage,Round(sum(calculatedlength)/5280,2)MILES
</E><E>,,sysdate Last_Refreshed_Ts, EWO.STATUS,  NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET)NTP_ESTIMATE, ADJUSTMENT_TOTAL_CAPITAL NTP_BEST_VIEW_AMOUNT
</E><E>,from Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,gisudm.pole@icgspdr_3gis  Pole
</E><E>,,VNADSPRD.Onef_Materials_EWO_As_Bulit_Comp_DT ABC
</E><E>,,vnadsprd.Onef_Materials_EWO_NTP_ACCEPT_DT NTP ,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where
</E><E>,EWO.COMPONENT_NFID=pole.createworkorderid
</E><E>,and EWO.COMPONENT_NFID=ABC.nfid(+)
</E><E>,and upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and ABC.RNK(+)=1
</E><E>,and EWO.COMPONENT_NFID=NTP.nfid(+)
</E><E>,and NTP.RNK(+)=1 
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,group by Dir.Director,Dir.Region,EWO.Market_Name,EWO.ONEFIBER_SUBTYPE,EWO.AFE, EWO.COMPONENT_NFID,AS_BUILT_COMP_DT,EWO.status, NVL(NTP_TOTAL_BUDGET_CAPITAL,NTP_TOTAL_BUDGET), ADJUSTMENT_TOTAL_CAPITAL,NTP_ACCEPT_DT
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,  SELECT COUNT(*) INTO V_EWO_MATERIAL_STG1 FROM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1; 
</E><E>,    SELECT COUNT(*) INTO V_EWO_MATERIAL_STG2 FROM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG2;
</E><E>,
</E><E>,    DBMS_OUTPUT.PUT_LINE (&apos;Count of VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1 # &apos;||V_EWO_MATERIAL_STG1);
</E><E>,    DBMS_OUTPUT.PUT_LINE (&apos;Count of VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG2 # &apos;||V_EWO_MATERIAL_STG2);
</E><E>,
</E><E>,	IF V_EWO_MATERIAL_STG1 = 0 AND V_EWO_MATERIAL_STG2 = 0 THEN 
</E><E>,    EXECUTE IMMEDIATE &apos;INSERT /*+ PARALLEL (T1, 16) */ INTO VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1 T1 SELECT /*+ PARALLEL (S, 16) */ * FROM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY&apos;;
</E><E>,    COMMIT;
</E><E>,	EXECUTE IMMEDIATE &apos;CREATE OR REPLACE SYNONYM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_SNM FOR VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1&apos;;
</E><E>,    END IF;
</E><E>,
</E><E>,
</E><E>,
</E><E>,    IF V_EWO_MATERIAL_STG1 = 0 AND V_EWO_MATERIAL_STG2 &lt;&gt; 0 THEN 
</E><E>,    DBMS_OUTPUT.PUT_LINE (&apos;Refresing  VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1&apos;);
</E><E>,    EXECUTE IMMEDIATE &apos;INSERT /*+ PARALLEL (T1, 16) */ INTO VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1 T1 SELECT /*+ PARALLEL (S, 16) */ * FROM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY&apos;;
</E><E>,    EXECUTE IMMEDIATE &apos;TRUNCATE TABLE VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG2 drop storage&apos;;
</E><E>,    COMMIT;
</E><E>,	EXECUTE IMMEDIATE &apos;CREATE OR REPLACE SYNONYM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_SNM FOR VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG1&apos;;
</E><E>,    END IF;
</E><E>,
</E><E>,    IF V_EWO_MATERIAL_STG1 &lt;&gt; 0 AND V_EWO_MATERIAL_STG2 = 0 THEN 
</E><E>,    DBMS_OUTPUT.PUT_LINE (&apos;Refresing  VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG2&apos;);
</E><E>,    EXECUTE IMMEDIATE &apos;INSERT /*+ PARALLEL (T2, 16) */ INTO VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG2 T2 SELECT /*+ PARALLEL (S, 16) */ * FROM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY&apos;;
</E><E>,    EXECUTE IMMEDIATE &apos;TRUNCATE TABLE VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY Drop Storage&apos;;
</E><E>,    COMMIT;
</E><E>,    EXECUTE IMMEDIATE &apos;CREATE OR REPLACE SYNONYM VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_SNM FOR VNADSPRD.ONEF_EWO_MATERIALS_SUMMARY_STG2&apos;;
</E><E>,	END IF;
</E><E>,
</E><E>,execute immediate &apos;Truncate table Vnadsprd.ONEF_EWO_MATERAIL_NO_FEATURES drop storage&apos;;
</E><E>,
</E><E>,insert into Vnadsprd.Onef_EWO_Materail_No_Features
</E><E>,(DIRECTOR, REGION, MARKET_NAME, EWO, EWO_SATUS, EWO_DIFFERAL_STATUS, PROJECT_START_DATE, PROJ_STATUS, REMAIN_CAPITAL_INV, REMAIN_EXPENSE_INV, LAST_REFRESHED_TS)
</E><E>,select director, Dir.region,EWO.market_name,COMPONENT_NFID EWO,Ewo.Status EWO_SATUS, 
</E><E>,Ewo.Status EWO_Differal_Status,Sysdate Project_Start_Date,Ewo.Status Proj_Status,AMT.REMAINING_TO_INVOICE_CAPITAL Remain_Capital_Inv, REMAINING_TO_INVOICE_EXPENSE Remain_Expense_Inv
</E><E>,,Sysdate Last_Refreshed_Ts
</E><E>,from  Vnadsprd.onef_Materials_EWOS_STG EWO
</E><E>,,vnadsprd.ONEF_DIRECTOR_MARKET_NAMES Dir
</E><E>,,wfm_nf.NF_PM_FIBER_BUDGET_MGMT@wfmaws AMT
</E><E>,where 1=1
</E><E>,and ewo.COMPONENT_NFID not in (select ewo from vnadsprd.ONEF_EWO_MATERIALS_SUMMARY)
</E><E>,and  upper(ewo.Market_name)=Upper(dir.Market(+))
</E><E>,and  EWO.COMPONENT_NFID=AMT.EWO_nfid(+)
</E><E>,;
</E><E>,
</E><E>,Commit;
</E><E>,
</E><E>,    /* Logging step to update session status */
</E><E>,
</E><E>,	UPDATE VNADSPRD.ONEF_SESS_STATUS_LOGS SET 
</E><E>,		ONEF_SESS_INTF_RUN_MODE = &apos;Completed&apos;,
</E><E>,		ONEF_SESS_LOG_MSG = &apos;Success&apos;,
</E><E>,		ONEF_SESS_END_DATE = TRUNC(SYSDATE),
</E><E>,		ONEF_SESS_END_TS = SYSTIMESTAMP,
</E><E>,		ONEF_SESS_TIME_TAKEN = ROUND(TO_NUMBER(TO_DATE(TO_CHAR(SYSTIMESTAMP,&apos;DD-MON-YYYY HH:MI:SS AM&apos;),&apos;DD-MON-YYYY HH:MI:SS AM&apos;) - 
</E><E>,		TO_DATE(TO_CHAR(ONEF_SESS_START_TS,&apos;DD-MON-YYYY HH:MI:SS AM&apos;),&apos;DD-MON-YYYY HH:MI:SS AM&apos;))*24*60*60),
</E><E>,		ONEF_SESS_STATUS = &apos;Success&apos; 
</E><E>,	WHERE 
</E><E>,		ONEF_SESS_INTF_ID = V_SESS_INTF_ID AND 
</E><E>,		ONEF_SESS_INTF_INST_ID = V_SESS_INST_ID AND 
</E><E>,        (ONEF_SESS_LOG_MSG IS NULL OR ONEF_SESS_STATUS IS NULL);
</E><E>,	COMMIT;
</E><E>,
</E><E>,	/* End of Logging step to update session status */
</E><E>,
</E><E>,	/* Logging step for Exception Catch - Hard Error */
</E><E>,
</E><E>,	EXCEPTION
</E><E>,	WHEN OTHERS THEN
</E><E>,      V_ERR_CODE := SQLCODE;
</E><E>,      V_ERR_MSG := SUBSTR(SQLERRM, 1, 500);
</E><E>,
</E><E>,	UPDATE VNADSPRD.ONEF_SESS_STATUS_LOGS SET 
</E><E>,		ONEF_SESS_INTF_RUN_MODE = &apos;Completed&apos;,
</E><E>,		ONEF_SESS_LOG_MSG = V_ERR_CODE||&apos; : &apos;||V_ERR_MSG,
</E><E>,		ONEF_SESS_END_DATE = TRUNC(SYSDATE),
</E><E>,		ONEF_SESS_END_TS = SYSTIMESTAMP,
</E><E>,		ONEF_SESS_TIME_TAKEN = ROUND(TO_NUMBER(TO_DATE(TO_CHAR(SYSTIMESTAMP,&apos;DD-MON-YYYY HH:MI:SS AM&apos;),&apos;DD-MON-YYYY HH:MI:SS AM&apos;) - 
</E><E>,		TO_DATE(TO_CHAR(ONEF_SESS_START_TS,&apos;DD-MON-YYYY HH:MI:SS AM&apos;),&apos;DD-MON-YYYY HH:MI:SS AM&apos;))*24*60*60),
</E><E>,		ONEF_SESS_STATUS = &apos;Failed&apos; 
</E><E>,	WHERE 
</E><E>,		ONEF_SESS_INTF_ID = V_SESS_INTF_ID AND 
</E><E>,		ONEF_SESS_INTF_INST_ID = V_SESS_INST_ID;
</E><E>,	COMMIT;
</E><E>,
</E><E>,
</E><E>,	/* End of Logging step for Exception Catch - Hard Error */
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,
</E><E>,End;</E>"