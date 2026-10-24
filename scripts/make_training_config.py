"""Create explicit chronological train/selection/calibration/test boundaries."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kronos_lab.data import load_csv


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv',required=True);p.add_argument('--output',default='output/training-config.json')
    p.add_argument('--run-dir',default='output/ablation');p.add_argument('--lookback',type=int,default=64)
    p.add_argument('--horizon',type=int,default=8);p.add_argument('--max-steps',type=int,default=2)
    p.add_argument('--epochs',type=int,default=1);p.add_argument('--device',default='cpu')
    p.add_argument('--model',default='NeoQuasar/Kronos-small')
    args=p.parse_args();df=load_csv(args.csv);n=len(df)
    cuts=[int(n*r) for r in (.4,.6,.8)]
    if min([cuts[0],cuts[1]-cuts[0],cuts[2]-cuts[1],n-cuts[2]])<args.lookback+args.horizon:
        p.error('Each partition needs at least lookback+horizon candles; fetch more data or shorten context')
    config={'mode':'two-stage','data_csv':args.csv,'timestamp_column':'timestamps',
        'train_end':df.timestamps.iloc[cuts[0]].isoformat(),'validation_end':df.timestamps.iloc[cuts[1]].isoformat(),
        'calibration_end':df.timestamps.iloc[cuts[2]].isoformat(),
        'test_end':(df.timestamps.iloc[-1]+__import__('pandas').Timedelta(nanoseconds=1)).isoformat(),
        'context_length':args.lookback,'horizon':args.horizon,'stride':args.horizon,
        'kronos_path':'vendor/Kronos','tokenizer_path':'NeoQuasar/Kronos-Tokenizer-base',
        'model_path':args.model,'output_dir':args.run_dir,'device':args.device,'seed':42,
        'batch_size':2,'epochs':args.epochs,'max_steps':args.max_steps,
        'tokenizer_learning_rate':2e-4,'predictor_learning_rate':1e-6,'gradient_clip':2.,'patience':3}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(config,indent=2)+'\n');print(f'Saved {output}')


if __name__=='__main__':main()
