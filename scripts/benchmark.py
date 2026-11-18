"""Measure local model responses and optionally a labelled speech recording."""
import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

from jarvis import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', help='Optional local recording for speech evaluation')
    parser.add_argument('--expected', help='Expected transcript for that recording')
    args = parser.parse_args()
    if args.audio and not args.expected:
        parser.error('--audio requires --expected')
    cfg = config.load()
    from jarvis import memory
    from jarvis.brain import Brain
    report = {'profile':cfg.get('performance_profile'), 'os':platform.system(),
              'python':platform.python_version(), 'processor':platform.machine(), 'responses':[]}
    try:
        import psutil
        report['ram_gib'] = round(psutil.virtual_memory().total / 1024**3, 2)
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        memory.APP_DIR = Path(tmp)
        memory.DB_PATH = Path(tmp) / 'benchmark.db'
        db = memory.Memory()
        try:
            brain = Brain(cfg, db)
            for assistant, prompt in [('jarvis','Rewrite this sentence clearly: We needs to finish the report today.'),
                                      ('tuki','Explain why visiting each of n items once takes O(n) time.')]:
                brain.assistant = assistant
                measurements = []
                brain.on_metrics = measurements.append
                started = time.perf_counter()
                answer = brain._chat([{'role':'user','content':prompt}], use_tools=False)
                report['responses'].append({'assistant':assistant, 'model':brain.model_used,
                    'elapsed_seconds':round(time.perf_counter()-started,3),
                    'stream_metrics':measurements, 'answer':answer.get('content','')})
        finally:
            db.db.close()
    if args.audio:
        from jarvis.voice import load_whisper
        model = load_whisper(cfg)
        started = time.perf_counter()
        segments, _ = model.transcribe(args.audio, language='en')
        text = ' '.join(segment.text.strip() for segment in segments)
        expected, actual = args.expected.lower().split(), text.lower().split()
        previous = list(range(len(actual)+1))
        for index, word in enumerate(expected,1):
            row = [index]
            for column, found in enumerate(actual,1):
                row.append(min(row[-1]+1,previous[column]+1,previous[column-1]+(word!=found)))
            previous=row
        report['speech']={'seconds':round(time.perf_counter()-started,3),'transcript':text,
                          'word_error_rate':previous[-1]/max(1,len(expected)),
                          'wake_word_detected':any(word in text.lower().split() for word in cfg.get('wake_words',[]))}
    folder=config.APP_DIR/'benchmarks'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/('Benchmark '+str(time.time_ns())+'.json')
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
