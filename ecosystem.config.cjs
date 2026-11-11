module.exports = {
  apps: [
    {
      name: "kokorotts",
      script: `${__dirname}/.venv/bin/python`,
      args: "-m kokorotts.server",
      cwd: __dirname,
      env: {
        HOST: "127.0.0.1",
        PORT: "7860",
        HF_HOME: `${__dirname}/persistent/models/huggingface`,
        KOKOROTTS_SETTINGS_PATH: `${__dirname}/persistent/app/settings.json`,
        KOKOROTTS_MCP_OUTPUT_DIR: `${__dirname}/persistent/mcp-output`,
        OMP_NUM_THREADS: "6",
        MKL_NUM_THREADS: "6",
        TORCH_NUM_THREADS: "6"
      },
      restart_delay: 3000,
      autorestart: true,
      max_restarts: 10
    }
  ]
};
