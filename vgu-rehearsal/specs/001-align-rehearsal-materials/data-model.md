# Artifact model

Slide: id,title,kicker,minutes,bullets,visual,speaker_notes,takeaway,sources. IDs unique per deck;minutes positive;sum exactly30/20;no unsupported historical numbers. Visual data and bullet/notes explanations refer to the same example.
NotebookResult: actual_path,source_hash,executed_cells,total_code_cells,output_count,error_count,status,elapsed_s. Worked requires error_count=0 and executed_cells=total_code_cells with saved output_count>0. Student incomplete is a distinct status.
Claim: wording,metric,population,primary_record,ownership,disposition. Only supported claims enter spoken historical results;unknown candidate assertions stay in the ledger.
RequirementEvidence: requirement_id,artifact_paths,check,observation,status. Status is verified,failed,or human_pending. Human_pending cannot be relabelled verified by file existence.
